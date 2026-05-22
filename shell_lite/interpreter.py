import concurrent.futures
import csv
import importlib
import json
import math
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from .ast_nodes import *
from .lexer import Lexer
from .parser import Parser

class ReturnException(Exception):
    def __init__(self, value):
        self.value = value

class StopException(Exception):
    pass

class SkipException(Exception):
    pass

class Environment:
    def __init__(self, parent=None, instance_data: Dict[str, Any] = None):
        self.variables: Dict[str, Any] = {}
        self.constants: set = set()
        self.parent = parent
        self.instance_data = instance_data

    def get(self, name: str) -> Any:
        if name in self.variables:
            return self.variables[name]
        if self.instance_data is not None and name in self.instance_data:
            return self.instance_data[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(f"Variable '{name}' is not defined.")

    def set(self, name: str, value: Any):
        if name in self.constants:
            raise RuntimeError(f"Cannot reassign constant '{name}'")
        
        # 1. Local variable shadowing or already existing
        if name in self.variables:
            self.variables[name] = value
            return
            
        # 2. Instance data property
        if self.instance_data is not None and name in self.instance_data:
            self.instance_data[name] = value
            return

        # 3. Parent scope (search for existing variable)
        curr = self.parent
        while curr:
            if name in curr.variables:
                if name in curr.constants:
                    raise RuntimeError(f"Cannot reassign constant '{name}'")
                curr.variables[name] = value
                return
            if curr.instance_data is not None and name in curr.instance_data:
                curr.instance_data[name] = value
                return
            curr = curr.parent
            
        # 4. Create new local variable
        self.variables[name] = value

    def set_const(self, name: str, value: Any):
        if name in self.variables:
            raise RuntimeError(f"Constant '{name}' already declared")
        self.variables[name] = value
        self.constants.add(name)

class PythonBridgeWrapper:
    def __init__(self, obj, name="<python_object>"):
        self._obj = obj
        self._name = name

    def __getattr__(self, key):
        if key == "_obj": return super()._obj
        try:
            attr = getattr(self._obj, key)
            if callable(attr):
                def wrapper(*args, **kwargs):
                    try:
                        unwrapped_args = [a._obj if isinstance(a, PythonBridgeWrapper) else a for a in args]
                        unwrapped_kwargs = {k: (v._obj if isinstance(v, PythonBridgeWrapper) else v) for k, v in kwargs.items()}
                        result = attr(*unwrapped_args, **unwrapped_kwargs)
                        if type(result) in (int, float, str, bool, type(None), list, dict, bytes):
                            return result
                        return PythonBridgeWrapper(result, name=f"{self._name}.{key}()")
                    except Exception as e:
                        raise RuntimeError(f"Python interop error calling '{self._name}.{key}': {e}")
                return wrapper
            if type(attr) in (int, float, str, bool, type(None), list, dict, bytes):
                return attr
            return PythonBridgeWrapper(attr, name=f"{self._name}.{key}")
        except AttributeError:
            raise AttributeError(f"Python object '{self._name}' has no member '{key}'")

    def __getitem__(self, key):
        res = self._obj[key]
        if type(res) in (int, float, str, bool, type(None), list, dict, bytes):
            return res
        return PythonBridgeWrapper(res, name=f"{self._name}[{key}]")

    def __setitem__(self, key, value):
        self._obj[key] = value

    def __len__(self):
        return len(self._obj)

    def __bool__(self):
        return bool(self._obj)

    def __add__(self, other):
        other_obj = other._obj if isinstance(other, PythonBridgeWrapper) else other
        res = self._obj + other_obj
        if type(res) in (int, float, str, bool, type(None), list, dict, bytes): return res
        return PythonBridgeWrapper(res)

    def __sub__(self, other):
        other_obj = other._obj if isinstance(other, PythonBridgeWrapper) else other
        res = self._obj - other_obj
        if type(res) in (int, float, str, bool, type(None), list, dict, bytes): return res
        return PythonBridgeWrapper(res)

    def __mul__(self, other):
        other_obj = other._obj if isinstance(other, PythonBridgeWrapper) else other
        res = self._obj * other_obj
        if type(res) in (int, float, str, bool, type(None), list, dict, bytes): return res
        return PythonBridgeWrapper(res)

    def __truediv__(self, other):
        other_obj = other._obj if isinstance(other, PythonBridgeWrapper) else other
        res = self._obj / other_obj
        if type(res) in (int, float, str, bool, type(None), list, dict, bytes): return res
        return PythonBridgeWrapper(res)

class LambdaFunction:
    def __init__(self, params: List[str], body, interpreter, name: Optional[str] = None):
        self.params = params
        self.body = body
        self.interpreter = interpreter
        self.closure_env = interpreter.current_env
        self.name = name

    def __call__(self, *args, **kwargs):
        old_env = self.interpreter.current_env
        inst = args[0] if (self.params and self.params[0] == 'self' and args and isinstance(args[0], Instance)) else None
        new_env = Environment(parent=self.closure_env, instance_data=inst.data if inst else None)

        for param, arg in zip(self.params, args):
            new_env.variables[param] = arg
        self.interpreter.current_env = new_env
        try:
            result = self.interpreter.visit_block(self.body)
        except ReturnException as e:
            result = e.value
        finally:
            self.interpreter.current_env = old_env
        return result

class Instance:
    def __init__(self, class_def: ClassDef, interpreter):
        self.class_def = class_def
        self.interpreter = interpreter
        self.data: Dict[str, Any] = {}
        for prop_name, default_node in class_def.properties:
            self.data[prop_name] = interpreter.visit(default_node) if default_node else None

    def get_method(self, name: str):
        for method in self.class_def.methods:
            if method.name == name:
                return LambdaFunction(['self'] + [a[0] for a in method.args], method.body, self.interpreter, name=method.name)
        return None
class JITTag:
    def __init__(self, name, attrs=None):
        self.name = name
        self.attrs = attrs or {}
        self.children = []
    def add(self, child):
        self.children.append(child)
    def __str__(self):
        attr_str = ''.join([f' {k}="{v}"' for k,v in self.attrs.items()])
        inner = ''.join([str(c) for c in self.children])
        if self.name in ('img', 'br', 'hr', 'input', 'meta', 'link'):
            return f'<{self.name}{attr_str} />'
        return f'<{self.name}{attr_str}>{inner}</{self.name}>'

def make_jit_tag_fn(name, interpreter):
    def fn(*args, **kwargs):
        attrs = dict(kwargs)
        content = []
        for arg in args:
            if isinstance(arg, dict):
                attrs.update(arg)
            elif isinstance(arg, LambdaFunction):
                t = JITTag(name, attrs)
                if interpreter.web_builder:
                    interpreter.web_builder[-1].add(t)
                interpreter.web_builder.append(t)
                try:
                    arg()
                finally:
                    interpreter.web_builder.pop()
                return t
            elif isinstance(arg, str) and '=' in arg and ' ' not in arg:
                k, v = arg.split('=', 1)
                attrs[k] = v
            else:
                content.append(arg)
        t = JITTag(name, attrs)
        for c in content:
            t.add(c)
        if interpreter.web_builder:
            interpreter.web_builder[-1].add(t)
        return t
    return fn

class Interpreter:
    def __init__(self):
        self.safe_mode = os.environ.get("SHL_SAFE") == "1"
        self._thread_local = threading.local()
        self.global_env = Environment()
        self.current_env = self.global_env
        self.functions: Dict[str, FunctionDef] = {}
        self.classes: Dict[str, ClassDef] = {}
        self._shared_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
        self.builtins = {
            'str': str, 'int': lambda x: int(float(x)) if x else 0, 'float': float, 'bool': bool,
            'list': list, 'len': len, 'range': lambda *args: list(range(*args)),
            'abs': abs, 'typeof': lambda x: type(x).__name__, 'print': print, 'say': print,
            'ask': input, 'sleep': time.sleep, 'exit': sys.exit, 'timestamp': time.time,
            'null': None, 'true': True, 'false': False, 'yes': True, 'no': False,
            'open': open,
            'py_exec': exec,
            'tuple': lambda x: tuple(x),
            'getattr': getattr,
            'add': lambda target, item: target.add(item) if isinstance(target, set) else target.append(item),
            'remove': lambda target, item: target.remove(item),
            'sum': sum,
            'split': lambda x, sep=None: x.split(sep) if sep else x.split(),
            'upper': lambda x: x.upper(),
            'lower': lambda x: x.lower(),
            'sort': lambda x: sorted(x),
            'count': lambda x, y=None: x.count(y) if y is not None else len(x),
            'xor': lambda a, b: a ^ b,
            'empty': lambda x: len(x) == 0,
            'ord': ord,
            'char': chr,
            'exists': os.path.exists,
            'json_parse': json.loads,
            'json_stringify': json.dumps,
            'contains': lambda obj, item: item in obj,
            'std_io_read': lambda path: open(path, 'r', encoding='utf-8').read(),
            'std_io_write': lambda path, content: open(path, 'w', encoding='utf-8').write(content),
            'std_io_append': lambda path, content: open(path, 'a', encoding='utf-8').write(content),
            'clear_dict': lambda d: d.clear(),
        }
        self.web_builder = []
        for t in ['div', 'p', 'h1', 'h2', 'h3', 'h4', 'span', 'a',
                  'img', 'button', 'input', 'form', 'ul', 'li',
                  'html', 'head', 'body', 'title', 'meta', 'link',
                  'script', 'style', 'br', 'hr', 'header', 'nav', 'footer',
                  'textarea', 'strong']:
            self.builtins[t] = make_jit_tag_fn(t, self)
        for k, v in self.builtins.items(): self.global_env.set(k, v)
        self._load_stdlib()

    @property
    def current_env(self):
        if not hasattr(self._thread_local, 'current_env'):
            self._thread_local.current_env = self.global_env
        return self._thread_local.current_env

    @current_env.setter
    def current_env(self, value):
        self._thread_local.current_env = value

    def _load_stdlib(self):
        stdlib_path = os.path.join(os.path.dirname(__file__), 'stdlib')
        if not os.path.exists(stdlib_path): return
        std_file = os.path.join(stdlib_path, 'std.shl')
        if os.path.exists(std_file):
            with open(std_file, 'r', encoding='utf-8') as f: source = f.read()
            try:
                nodes = Parser(source).parse()
                self.visit_block(nodes)
            except Exception as e: print(f"Warning: Failed to load stdlib: {e}")

    def visit(self, node: Node) -> Any:
        if node is None: return None
        method_name = f'visit_{type(node).__name__}'
        visitor = getattr(self, method_name, self.generic_visit)
        
        try:
            return visitor(node)
        except AttributeError as e:
            if "'Number' object has no attribute 'name'" in str(e):
                print(f"DEBUG Error in {method_name} for node: {node}")
            raise
        except Exception as e:
            raise

    def generic_visit(self, node: Node):
        raise Exception(f'No visit_{type(node).__name__} method')

    def visit_block(self, body: List[Node]) -> Any:
        result = None
        for stmt in body: result = self.visit(stmt)
        return result

    def visit_Number(self, node: Number): return node.value
    def visit_String(self, node: String): return node.value
    def visit_Boolean(self, node: Boolean): return node.value
    def visit_VarAccess(self, node: VarAccess):
        val = self.current_env.get(node.name)
        if isinstance(val, LambdaFunction) and len(val.params) == 0 and getattr(val, 'name', None) is not None:
            return val()
        return val
    def visit_Assign(self, node: Assign):
        val = self.visit(node.value)
        self.current_env.set(node.name, val)
        return val
    def visit_TypedAssign(self, node: TypedAssign): return self.visit_Assign(Assign(node.name, node.value))
    def visit_ConstAssign(self, node: ConstAssign):
        val = self.visit(node.value)
        self.current_env.set_const(node.name, val)
        return val

    def visit_BinOp(self, node: BinOp):
        left = self.visit(node.left)
        if node.op == '.':
            if isinstance(left, Instance):
                if isinstance(node.right, Call):
                    method = left.get_method(node.right.name)
                    if method:
                        args = [self.visit(a) for a in node.right.args]
                        kwargs = {k: self.visit(v) for k, v in node.right.kwargs} if node.right.kwargs else {}
                        return method(left, *args, **kwargs)
                else:
                    method = left.get_method(node.right.name)
                    if method: return lambda *args, **kwargs: method(left, *args, **kwargs)
                    return left.data.get(node.right.name)
            if isinstance(node.right, Call):
                attr = getattr(left, node.right.name)
                args = [self.visit(a) for a in node.right.args]
                kwargs = {k: self.visit(v) for k, v in node.right.kwargs} if node.right.kwargs else {}
                return attr(*args, **kwargs)
            return getattr(left, node.right.name)
        right = self.visit(node.right)
        ops = {'+': lambda a, b: a + b, '-': lambda a, b: a - b, '*': lambda a, b: a * b, '/': lambda a, b: a / b, '%': lambda a, b: a % b, '==': lambda a, b: a == b, '!=': lambda a, b: a != b, '<': lambda a, b: a < b, '>': lambda a, b: a > b, '<=': lambda a, b: a <= b, '>=': lambda a, b: a >= b, 'and': lambda a, b: a and b, 'or': lambda a, b: a or b, 'in': lambda a, b: a in b, 'not in': lambda a, b: a not in b}
        return ops[node.op](left, right)

    def visit_UnaryOp(self, node: UnaryOp):
        right = self.visit(node.right)
        return (-right if node.op == '-' else not right)

    def visit_If(self, node: If):
        if self.visit(node.condition): return self.visit_block(node.body)
        if node.else_body: return self.visit_block(node.else_body)
        return None

    def visit_While(self, node: While):
        while self.visit(node.condition):
            try: self.visit_block(node.body)
            except StopException: break
            except SkipException: continue
        return None

    def visit_ForIn(self, node: ForIn):
        for val in self.visit(node.iterable):
            self.current_env.set(node.var_name, val)
            try: self.visit_block(node.body)
            except StopException: break
            except SkipException: continue
        return None

    def visit_Repeat(self, node: Repeat):
        count = self.visit(node.count)
        for _ in range(int(count)):
            try: self.visit_block(node.body)
            except StopException: break
            except SkipException: continue
        return None

    def visit_FunctionDef(self, node: FunctionDef):
        lf = LambdaFunction([a[0] for a in node.args], node.body, self, name=node.name)
        self.current_env.set(node.name, lf)
        return lf

    def visit_Call(self, node: Call):
        func = self.current_env.get(node.name)
        args = [self.visit(a) for a in node.args]
        if node.body: args.append(LambdaFunction([], node.body, self, name=None))
        kwargs = {k: self.visit(v) for k, v in node.kwargs} if node.kwargs else {}
        return func(*args, **kwargs)

    def visit_Return(self, node: Return): raise ReturnException(self.visit(node.value))
    def visit_Print(self, node: Print):
        val = self.visit(node.expression)
        print(val)
        return val
    def visit_ListVal(self, node: ListVal): return [self.visit(e) for e in node.elements]
    def visit_Dictionary(self, node: Dictionary):
        return {self.visit(k): self.visit(v) for k, v in node.pairs}
    def visit_Try(self, node: Try):
        try: return self.visit_block(node.try_body)
        except Exception as e:
            self.current_env.set(node.catch_var, str(e))
            return self.visit_block(node.catch_body)
    def visit_PythonImport(self, node: PythonImport):
        module = importlib.import_module(node.module_name)
        wrapper = PythonBridgeWrapper(module, name=node.module_name)
        self.global_env.set(node.alias or node.module_name, wrapper)
        return wrapper
    def visit_FromImport(self, node: FromImport):
        module = importlib.import_module(node.module_name)
        for name, alias in node.names:
            attr = getattr(module, name)
            if not type(attr) in (int, float, str, bool, type(None), list, dict):
                 attr = PythonBridgeWrapper(attr, name=f"{node.module_name}.{name}")
            self.global_env.set(alias or name, attr)
    def visit_Stop(self, node: Stop): raise StopException()
    def visit_Skip(self, node: Skip): raise SkipException()
    def visit_Import(self, node: Import):
        path = node.path
        if not path.endswith('.shl'): path += '.shl'
        search_paths = [os.getcwd(), os.path.join(os.path.dirname(__file__), 'stdlib')]
        for p in search_paths:
            full_path = os.path.join(p, path)
            if os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8') as f: source = f.read()
                nodes = Parser(source).parse()
                return self.visit_block(nodes)
        raise FileNotFoundError(f"Module {node.path} not found")

    def visit_ClassDef(self, node: ClassDef):
        self.classes[node.name] = node
        
        def constructor(*args, **kwargs):
            inst = Instance(node, self)
            for i, arg in enumerate(args):
                if i < len(node.properties):
                    prop_name = node.properties[i][0]
                    inst.data[prop_name] = arg
            return inst
            
        self.current_env.set(node.name, constructor)
        return None
    def visit_Instantiation(self, node: Instantiation):
        cls = self.classes[node.class_name]
        inst = Instance(cls, self)
        self.current_env.set(node.var_name, inst)
        return inst
    def visit_PropertyAccess(self, node: PropertyAccess):
        inst = self.current_env.get(node.instance_name)
        if isinstance(inst, Instance): return inst.data.get(node.property_name)
        return getattr(inst, node.property_name)
    def visit_PropertyAssign(self, node: PropertyAssign):
        inst = self.current_env.get(node.instance_name)
        val = self.visit(node.value)
        if isinstance(inst, Instance): inst.data[node.property_name] = val
        else: setattr(inst, node.property_name, val)
        return val
    def visit_MethodCall(self, node: MethodCall):
        inst = self.current_env.get(node.instance_name)
        args = [self.visit(a) for a in node.args]
        if isinstance(inst, Instance):
            method = inst.get_method(node.method_name)
            return method(inst, *args)
        return getattr(inst, node.method_name)(*args)
    def visit_IndexAccess(self, node: IndexAccess):
        obj = self.visit(node.obj)
        idx = self.visit(node.index)
        return obj[idx]
    def visit_IndexAssign(self, node: IndexAssign):
        obj = self.visit(node.obj)
        idx = self.visit(node.index)
        val = self.visit(node.value)
        obj[idx] = val
        return val
    def visit_Spawn(self, node: Spawn):
        if not isinstance(node.call, Call):
            raise Exception("Spawn requires a function call")
        func = self.current_env.get(node.call.name)
        args = [self.visit(a) for a in node.call.args]
        if node.call.body:
            args.append(LambdaFunction([], node.call.body, self, name=None))
        kwargs = {k: self.visit(v) for k, v in node.call.kwargs} if node.call.kwargs else {}
        
        def run_threaded():
            try:
                func(*args, **kwargs)
            except Exception as e:
                import traceback
                print(f"[Spawn Thread Error]: {e}")
                traceback.print_exc()
        return self._shared_executor.submit(run_threaded)
    def visit_Await(self, node: Await):
        f = self.visit(node.task)
        return f.result() if hasattr(f, 'result') else f
    def visit_Match(self, node: Match):
        v = self.visit(node.match_expr)
        for ce, b in node.cases:
            if v == self.visit(ce): return self.visit_block(b)
        return self.visit_block(node.default_case) if node.default_case else None

    def visit_FileRead(self, node: FileRead):
        path = self.visit(node.path)
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def visit_FileWrite(self, node: FileWrite):
        path = self.visit(node.path)
        content = self.visit(node.content)
        with open(path, node.mode, encoding='utf-8') as f:
            f.write(content)
        return None
