import concurrent.futures
import csv
import functools
import importlib
import json
import math
import os
import queue
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time

try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog
    _HAS_TK = True
except ImportError:
    _HAS_TK = False
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List

from .ast_nodes import *
from .lexer import Lexer
from .parser_gbp import GeometricBindingParser

try:
    import keyboard
    import mouse
    import pyperclip
    from plyer import notification
except ImportError:
    pass
class Environment:
    """
    -----Purpose: Represents the variable and constant binding environment at a
                  specific scope level during execution.
    """
    def __init__(self, parent=None):
        self.variables: Dict[str, Any] = {}
        self.constants: set = set()
        self.parent = parent
    def get(self, name: str) -> Any:
        if name in self.variables:
            return self.variables[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(f"Variable '{name}' is not defined.")
    def set(self, name: str, value: Any):
        if name in self.constants:
            raise RuntimeError(f"Cannot reassign constant '{name}'")
        # Update existing variable in current or parent scope
        curr = self
        while curr:
            if name in curr.variables:
                if name in curr.constants:
                    raise RuntimeError(f"Cannot reassign constant '{name}'")
                curr.variables[name] = value
                return
            curr = curr.parent
        # Not found, create in current scope
        self.variables[name] = value
    def set_const(self, name: str, value: Any):
        if name in self.variables:
            raise RuntimeError(f"Constant '{name}' already declared")
        self.variables[name] = value
        self.constants.add(name)
class Namespace:
    def __init__(self, name, members):
        self._name = name
        self._members = members
    def __getattr__(self, key):
        if key in self._members: return self._members[key]
        raise AttributeError(f"Module '{self._name}' has no member '{key}'")
    def __getitem__(self, key): return self._members[key]
    def __repr__(self): return f"<Module '{self._name}'>"

class ReturnException(Exception):
    def __init__(self, value):
        self.value = value
class StopException(Exception):
    pass
class SkipException(Exception):
    pass
class ShellLiteError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)
class LambdaFunction:
    def __init__(self, params: List[str], body, interpreter):
        self.params = params
        self.body = body
        self.interpreter = interpreter
        self.closure_env = interpreter.current_env
    def __call__(self, *args):
        if len(args) != len(self.params):
            raise TypeError(f"Lambda expects {len(self.params)} args, got {len(args)}")
        old_env = self.interpreter.current_env
        new_env = Environment(parent=self.closure_env)
        for param, arg in zip(self.params, args):
            new_env.set(param, arg)
        self.interpreter.current_env = new_env
        try:
            result = self.interpreter.visit(self.body)
        finally:
            self.interpreter.current_env = old_env
        return result
class Instance:
    """
    -----Purpose: Represents an instantiated struct/class with bounded data.
    """
    def __init__(self, class_def: ClassDef):
        self.class_def = class_def
        self.data: Dict[str, Any] = {}
class Tag:
    """
    -----Purpose: A node representation to build DSL tree structures (like HTML).
    """
    def __init__(self, name: str, attrs: Dict[str, Any] = None):
        self.name = name
        self.attrs = attrs or {}
        self.children: List[Any] = []
    def add(self, child):
        if isinstance(child, Tag):
             if any(c is child for c in self.children):
                 return
        self.children.append(child)
    def __str__(self):
        attr_str = ""
        for k, v in self.attrs.items():
            attr_str += f' {k}="{v}"'
        inner = ""
        for child in self.children:
            inner += str(child)
        if self.name in ('img', 'br', 'hr', 'input', 'meta', 'link'):
            return f"<{self.name}{attr_str} />"
        return f"<{self.name}{attr_str}>{inner}</{self.name}>"
class WebBuilder:
    """
    -----Purpose: Manages a stack of Tags to sequentially build declarative Web UI.
    """
    def __init__(self, interpreter):
        self.stack: List[Tag] = []
        self.interpreter = interpreter
    def push(self, tag: Tag):
        if self.stack:
            self.stack[-1].add(tag)
        self.stack.append(tag)
    def pop(self):
        if not self.stack: return None
        return self.stack.pop()
    def add_text(self, text: str):
        if self.stack:
            self.stack[-1].add(text)
        else:
            pass
class Interpreter:
    """
    -----Purpose: The core tree walking interpreter that executes AST nodes.
    """
    def __init__(self):
        self.safe_mode = os.environ.get("SHL_SAFE") == "1"
        self.global_env = Environment()
        self.global_env.set('str', str)
        self.global_env.set('int', int)
        self.global_env.set('float', float)
        self.global_env.set('list', list)
        self.global_env.set('len', len)
        self.global_env.set('None', None)
        self.global_env.set('null', None)
        self.global_env.set('wait', time.sleep)
        self.global_env.set('append', self._builtin_smart_add)
        self.global_env.set('push', self._builtin_smart_add)
        self.global_env.set('remove', lambda l, x: l.remove(x))
        self.global_env.set('empty', lambda l: len(l) == 0)
        self.global_env.set('contains', lambda l, x: x in l)
        self.global_env.set('abs', abs)
        self.current_env = self.global_env
        self.functions: Dict[str, FunctionDef] = {}
        self.classes: Dict[str, ClassDef] = {}
        self.http_routes = []
        self.middleware_routes = []
        self.static_routes = {}
        self.web = WebBuilder(self)
        self.db_conn = None
        self._shared_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
        self._named_locks: Dict[str, threading.Lock] = {}
        self.models: Dict[str, 'ModelDef'] = {}
        self.builtins = {
            'str': str, 'int': int, 'float': float, 'bool': bool,
            'list': list, 'len': len,
            'range': lambda *args: list(range(*args)),
            'abs': abs,
            'typeof': lambda x: type(x).__name__,
            'run': self.builtin_run,
            'read': self.builtin_read,
            'write': self.builtin_write,
            'json_parse': self.builtin_json_parse,
            'json_stringify': self.builtin_json_stringify,
            'sum': sum,
            'even': lambda x: x % 2 == 0,
            'prime': lambda x: x > 1 and all(x % i != 0 for i in range(2, int(x**0.5) + 1)),
            'print': print,
            'add': self._builtin_smart_add,
            'ask': input,
            'print': print,
            'split': self._builtin_split,
            'join': lambda lst, d="": d.join(str(x) for x in lst),
            'replace': lambda s, old, new: s.replace(old, new),
            'upper': self._builtin_upper,
            'lower': lambda s: s.lower(),
            'trim': lambda s: s.strip(),
            'startswith': lambda s, p: s.startswith(p),
            'endswith': lambda s, p: s.endswith(p),
            'sum_range': self._builtin_sum_range,
            'range_list': self._builtin_range_list,
            'find': lambda s, sub: s.find(sub),
            'char': chr, 'ord': ord,
            'append': self._builtin_smart_add,
            'push': self._builtin_smart_add,
            'count': len,
            'remove': lambda l, x: l.remove(x),
            'pop': lambda l, idx=-1: l.pop(idx),
            'get': lambda l, idx: l[idx],
            'set': lambda l, idx, val: l.__setitem__(idx, val) or l,
            'sort': lambda l: sorted(l),
            'reverse': lambda l: list(reversed(l)),
            'slice': lambda l, start, end=None: l[start:end],
            'contains': lambda l, x: x in l,
            'index': lambda l, x: l.index(x) if x in l else -1,
            'exists': os.path.exists,
            'delete': os.remove,
            'copy': shutil.copy,
            'rename': os.rename,
            'mkdir': lambda p: os.makedirs(p, exist_ok=True),
            'listdir': os.listdir,
            'http_get': self.builtin_http_get,
            'http_post': self.builtin_http_post,
            'random': random.random,
            'randint': random.randint,
            'sleep': time.sleep,
            'now': lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'timestamp': time.time,
            'unique': lambda l: list(dict.fromkeys(l)),
            'first': lambda l: l[0] if l else None,
            'last': lambda l: l[-1] if l else None,
            'empty': lambda x: len(x) == 0 if hasattr(x, '__len__') else x is None,
            'keys': lambda d: list(d.keys()),
            'values': lambda d: list(d.values()),
            'items': lambda d: list(d.items()),
            'push': self._builtin_push,
            'remove': lambda lst, item: lst.remove(item),
            'Set': set,
            'show': print,
            'say': print,
            'today': lambda: datetime.now().strftime("%Y-%m-%d"),
        }
        self.math_members = {
            'abs': abs, 'min': min, 'max': max,
            'round': round, 'pow': pow, 'sum': sum,
            'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'floor': math.floor, 'ceil': math.ceil, 'sqrt': math.sqrt,
            'log': math.log, 'log10': math.log10, 'exp': math.exp,
            'pi': math.pi, 'e': math.e,
            'lerp': lambda a, b, t: a + (b - a) * t,
            'clamp': lambda v, lo, hi: max(lo, min(v, hi))
        }
        
        self._init_std_modules()


        tags = [
            'div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'span', 'a', 'img', 'button', 'input', 'form',
            'ul', 'li', 'ol', 'table', 'tr', 'td', 'th',
            'html', 'head', 'body', 'title', 'meta', 'link',
            'script', 'style', 'br', 'hr',
            'header', 'footer', 'section', 'article', 'nav', 'aside', 'main',
            'strong', 'em', 'code', 'pre', 'blockquote', 'iframe', 'canvas', 'svg',
            'css', 'textarea', 'label'
        ]
        for t in tags:
            self.builtins[t] = self._make_tag_fn(t)
        self.builtins['env'] = lambda name: os.environ.get(str(name), None)
        self.builtins['int'] = lambda x: int(float(x)) if x else 0
        self.builtins['str'] = lambda x: str(x)
        class TimeWrapper:
            def now(self):
                return str(int(time.time()))
        self.builtins['time'] = TimeWrapper()
        for k, v in self.builtins.items():
            self.global_env.set(k, v)
    def _make_tag_fn(self, tag_name):
        def tag_fn(*args, **kwargs):
            attrs = {}
            attrs.update(kwargs)
            content = []
            for arg in args:
                if isinstance(arg, dict):
                    attrs.update(arg)
                elif isinstance(arg, str):
                    if '=' in arg and ' ' not in arg and arg.split('=')[0].isalnum():
                        k, v = arg.split('=', 1)
                        attrs[k] = v
                    else:
                        content.append(arg)
                else:
                    content.append(str(arg))
            t = Tag(tag_name, attrs)
            for c in content:
                t.add(c)
            return t
        return tag_fn
    def _builtin_map(self, lst, func):
        if callable(func):
            return [func(x) for x in lst]
        raise TypeError("map requires a callable")
    def _builtin_filter(self, lst, func):
        if callable(func):
            return [x for x in lst if func(x)]
        raise TypeError("filter requires a callable")
    def _builtin_reduce(self, lst, func, initial=None):
        if callable(func):
            if initial is not None:
                return functools.reduce(func, lst, initial)
            return functools.reduce(func, lst)
        raise TypeError("reduce requires a callable")
    def _builtin_push(self, lst, item):
        lst.append(item)
        return None
    def _builtin_split(self, s, sep=None):
        return str(s).split(sep)
    def _builtin_sum_range(self, start, end):
        return sum(range(int(start), int(end)))
    def _builtin_range_list(self, start, end):
        return list(range(int(start), int(end)))
    def _builtin_smart_add(self, target, val):
        if isinstance(target, list):
            target.append(val)
            return target
        elif isinstance(target, (int, float, str)):
            return target + val
        else:
            raise TypeError(f"Cannot add to {type(target).__name__}")
    def _init_std_modules(self):
        self.std_modules = {
            'math': Namespace('math', self.math_members),
            'time': Namespace('time', {
                'time': time.time,
                'sleep': time.sleep,
                'date': lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'year': lambda: datetime.now().year,
                'month': lambda: datetime.now().month,
                'day': lambda: datetime.now().day,
            }),
            'http': Namespace('http', {
                'get': self._http_get,
                'post': self._http_post
            }),
            'env': Namespace('env', {
                'get': lambda k, d=None: os.environ.get(k, d),
                'set': lambda k, v: os.environ.__setitem__(k, str(v)),
                'all': lambda: dict(os.environ),
                'os': os.name,
                'platform': sys.platform,
            }),
            'path': Namespace('path', {
                'join': os.path.join,
                'basename': os.path.basename,
                'exists': os.path.exists,
                'isdir': os.path.isdir,
                'abspath': os.path.abspath,
            }),
            'color': Namespace('color', {
                'red': lambda s: f"\033[91m{s}\033[0m",
                'green': lambda s: f"\033[92m{s}\033[0m",
                'blue': lambda s: f"\033[94m{s}\033[0m",
                'bold': lambda s: f"\033[1m{s}\033[0m",
                'reset': "\033[0m",
            }),
            're': Namespace('re', {
                'match': lambda p, s: bool(re.match(p, s)),
                'search': lambda p, s: re.search(p, s).group() if re.search(p, s) else None,
                'replace': lambda p, r, s: re.sub(p, r, s),
            }),
        }
    def _http_get(self, url):
        with urllib.request.urlopen(url) as response:
            return response.read().decode('utf-8')
    def _http_post(self, url, data):
        if isinstance(data, str):
            json_data = data.encode('utf-8')
        else:
            json_data = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=json_data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            return response.read().decode('utf-8')
    def visit(self, node: Node) -> Any:
        if node is None:
            return None
        try:
            method_name = f'visit_{type(node).__name__}'
            visitor = getattr(self, method_name, self.generic_visit)
            return visitor(node)
        except ReturnException:
            raise
        except Exception as e:
            if not hasattr(e, 'line') and hasattr(node, 'line'):
                e.line = node.line
            raise e
    def generic_visit(self, node: Node):
        raise Exception(f'No visit_{type(node).__name__} method')
    def visit_statement_list(self, statements: List[Node]):
        """
        -----Purpose: Executes a list of statements in order.
        """
        results = []
        for stmt in statements:
            results.append(self.visit(stmt))
        return results[-1] if results else None
    def visit_Number(self, node: Number):
        """
        -----Purpose: Returns the value of a numeric literal node.
        """
        return node.value
    def visit_String(self, node: String):
        """
        -----Purpose: Returns the value of a string literal node.
        """
        return node.value
    def visit_Boolean(self, node: Boolean):
        """
        -----Purpose: Returns the value of a boolean literal node.
        """
        return node.value
    def visit_ListVal(self, node: ListVal):
        """
        -----Purpose: Evaluates a list literal, including spread operations.
        """
        result = []
        for e in node.elements:
            if isinstance(e, Spread):
                spread_val = self.visit(e.value)
                if not isinstance(spread_val, list):
                    raise TypeError(
                        f"Spread operator requires a list, "
                        f"got {type(spread_val).__name__}"
                    )
                result.extend(spread_val)
            else:
                result.append(self.visit(e))
        return result
    def visit_FileRead(self, node: FileRead):
        """
        -----Purpose: Reads a file and returns its content as a string.
        """
        path = self.visit(node.path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"File '{path}' not found.")
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    def visit_Dictionary(self, node: Dictionary):
        """
        -----Purpose: Evaluates a dictionary literal.
        """
        return {self.visit(k): self.visit(v) for k, v in node.pairs}
    def visit_PropertyAssign(self, node: PropertyAssign):
        """
        -----Purpose: Assigns a value to an object or dictionary property.
        """
        instance = self.current_env.get(node.instance_name)
        val = self.visit(node.value)
        if isinstance(instance, Instance):
            instance.data[node.property_name] = val
            return val
        elif isinstance(instance, dict):
            instance[node.property_name] = val
            return val
        else:
            raise TypeError(
                f"Cannot assign property '{node.property_name}' "
                f"of non-object '{node.instance_name}'"
            )
    def visit_VarAccess(self, node: VarAccess):
        """
        -----Purpose: Retrieves the value of a variable or builtin function.
        """
        try:
            return self.current_env.get(node.name)
        except NameError:
            if node.name in self.builtins:
                val = self.builtins[node.name]
                if node.name in ('random', 'time_now', 'date_str'):
                    return val()
                return val
            if node.name in self.functions:
                return self.visit_Call(Call(node.name, []))
            raise
    def visit_Assign(self, node: Assign):
        """
        -----Purpose: Assigns a value to a variable in the current environment.
        """
        value = self.visit(node.value)
        self.current_env.set(node.name, value)
        return value
    _TYPE_MAP = {
        'int': int, 'integer': int,
        'float': float, 'decimal': float, 'number': float,
        'str': str, 'string': str, 'text': str,
        'bool': bool, 'boolean': bool,
        'list': list, 'array': list,
        'dict': dict, 'map': dict,
    }

    def visit_TypedAssign(self, node: TypedAssign):
        """
        -----Purpose: Assigns a value with an optional static type check.
                      Raises TypeError if the value doesn't match the declared type.
        """
        value = self.visit(node.value)
        expected = self._TYPE_MAP.get(node.type_hint)
        if expected is not None and not isinstance(value, expected):
            try:
                value = expected(value)
            except (ValueError, TypeError):
                raise TypeError(
                    f"Type error: '{node.name}' declared as '{node.type_hint}' "
                    f"but got {type(value).__name__} ({value!r})"
                )
        self.current_env.set(node.name, value)
        return value
    def visit_IndexAccess(self, node: IndexAccess):
        """
        -----Purpose: Evaluates an index/key access on list/dict.
        """
        obj = self.visit(node.obj)
        index = self.visit(node.index)
        try:
            return obj[index]
        except (IndexError, KeyError, TypeError) as e:
            raise RuntimeError(f"Index access error: {e}")
    def visit_IndexAssign(self, node: IndexAssign):
        """
        -----Purpose: Assigns a value at an index/key of list/dict.
        """
        obj = self.visit(node.obj)
        index = self.visit(node.index)
        value = self.visit(node.value)
        try:
            obj[index] = value
            return value
        except (IndexError, KeyError, TypeError) as e:
            raise RuntimeError(f"Index assignment error: {e}")
    def visit_BinOp(self, node: BinOp):
        """
        -----Purpose: Evaluates a binary operation between two nodes.
        """
        if node.op == '.':
            left = self.visit(node.left)
            if isinstance(node.right, VarAccess):
                attr = node.right.name
                if hasattr(left, attr): return getattr(left, attr)
                if hasattr(left, 'get'): return left.get(attr)
                
                if isinstance(left, Instance):
                    if attr in left.data:
                        return left.data[attr]
                
                raise AttributeError(f"Member '{attr}' not found on {left}")
            elif isinstance(node.right, Call):
                func = None
                attr = node.right.name
                # Support 'trim' as an alias for 'strip' on strings
                if isinstance(left, str) and attr == 'trim':
                    attr = 'strip'
                if hasattr(left, attr):
                    func = getattr(left, attr)
                elif hasattr(left, 'get'):
                    func = left.get(attr)
                
                if not func and isinstance(left, Instance):
                    method_node = self._find_method(left.class_def, attr)
                    if method_node:
                        args = [self.visit(a) for a in node.right.args]
                        old_env = self.current_env
                        new_env = Environment(parent=self.global_env)
                        for k, v in left.data.items():
                            new_env.set(k, v)
                        for i, (arg_name, default_node, type_hint) in enumerate(method_node.args):
                            if i < len(args):
                                val = args[i]
                            elif default_node is not None:
                                val = self.visit(default_node)
                            else:
                                raise TypeError(f"Missing arg '{arg_name}' for method '{attr}'")
                            new_env.set(arg_name, val)
                        self.current_env = new_env
                        ret_val = None
                        try:
                            for stmt in method_node.body:
                                self.visit(stmt)
                        except ReturnException as e:
                            ret_val = e.value
                        finally:
                            for k in left.data.keys():
                                if k in new_env.variables:
                                    left.data[k] = new_env.variables[k]
                            self.current_env = old_env
                        return ret_val

                if not func:
                    raise AttributeError(f"Method '{attr}' not found")
                args = [self.visit(a) for a in node.right.args]
                kwargs = {}
                if getattr(node.right, 'kwargs', None):
                    for k, v in node.right.kwargs:
                        kwargs[k] = self.visit(v)
                return func(*args, **kwargs)
            raise SyntaxError(f"Invalid member access: {node.right}")

        left = self.visit(node.left)
        right = self.visit(node.right)
        try:
            if node.op == '+':
                if isinstance(left, str) or isinstance(right, str):
                    return str(left) + str(right)
                if isinstance(left, list) and isinstance(right, list):
                    return left + right
                return left + right
            elif node.op == '-': return left - right
            elif node.op == '*': return left * right
            elif node.op == '/': return left / right
            elif node.op == '%': return left % right
            elif node.op == '==': return left == right
            elif node.op == '!=': return left != right
            elif node.op == '<': return left < right
            elif node.op == '>': return left > right
            elif node.op == '<=': return left <= right
            elif node.op == '>=': return left >= right
            elif node.op == 'in': return left in right
            elif node.op == 'not in': return left not in right
            elif node.op == 'and': return left and right
            elif node.op == 'or': return left or right
            elif node.op == 'matches':
                return bool(re.search(str(right), str(left)))
            else:
                raise Exception(f"Unknown operator: {node.op}")
        except TypeError as e:
            raise e
    def visit_UnaryOp(self, node: UnaryOp):
        """
        -----Purpose: Evaluates a unary operation
        """
        val = self.visit(node.right)
        if node.op == 'not':
            return not val
        elif node.op == '-':
            return -val
        return val
    def visit_Print(self, node: Print):
        """
        -----Purpose: Evaluates and prints a expression with optional styling.
        """
        value = self.visit(node.expression)
        if node.color or node.style:
            colors = {
                'red': '91', 'green': '92', 'yellow': '93', 'blue': '94',
                'magenta': '95', 'cyan': '96'
            }
            code_parts = []
            if node.style == 'bold':
                code_parts.append('1')
            if node.color and node.color.lower() in colors:
                code_parts.append(colors[node.color.lower()])
            if code_parts:
                ansi_code = "\033[" + ";".join(code_parts) + "m"
                print(f"{ansi_code}{value}\033[0m", flush=True)
                return value
        print(value, flush=True)
        return value
    def visit_If(self, node: If):
        """
        -----Purpose: Evaluates an if/elif/else conditional branch.
        """
        condition = self.visit(node.condition)
        if condition:
            for stmt in node.body:
                self.visit(stmt)
        elif node.else_body:
            for stmt in node.else_body:
                self.visit(stmt)
    def visit_Match(self, node):
        """
        -----Purpose: Evaluates a pattern matching (when/is/otherwise) block.
        """
        match_val = self.visit(node.match_expr)
        for case_expr, case_body in node.cases:
            case_val = self.visit(case_expr)
            if match_val == case_val:
                for stmt in case_body:
                    self.visit(stmt)
                return
        if node.default_case:
            for stmt in node.default_case:
                self.visit(stmt)
    def visit_For(self, node: For):
        """
        -----Purpose: Evaluates a numeric for loop.
        """
        count = self.visit(node.count)
        if not isinstance(count, int):
            raise TypeError(
                f"Loop count must be an integer, got {type(count)}"
            )
        for _ in range(count):
            try:
                for stmt in node.body:
                    self.visit(stmt)
            except StopException:
                break
            except SkipException:
                continue
            except ReturnException:
                raise



    def visit_Input(self, node: Input):
        """
        -----Purpose: Prompts the user for input.
        """
        if node.prompt:
            return input(node.prompt)
        return input()
    def visit_While(self, node: While):
        """
        -----Purpose: Evaluates a while loop until the condition is false.
        """
        while self.visit(node.condition):
            try:
                for stmt in node.body:
                    self.visit(stmt)
            except StopException:
                break
            except SkipException:
                continue
            except ReturnException:
                raise
    def visit_Try(self, node: Try):
        """
        -----Purpose: Evaluates a try-catch block for local error handling.
        """
        try:
            for stmt in node.try_body:
                self.visit(stmt)
        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'message'):
                error_msg = e.message
            self.current_env.set(node.catch_var, error_msg)
            for stmt in node.catch_body:
                self.visit(stmt)
    def visit_TryAlways(self, node: TryAlways):
        """
        -----Purpose: Evaluates a try-catch-always block.
        """
        try:
            try:
                for stmt in node.try_body:
                    self.visit(stmt)
            except Exception as e:
                error_msg = str(e)
                if hasattr(e, 'message'):
                    error_msg = e.message
                self.current_env.set(node.catch_var, error_msg)
                for stmt in node.catch_body:
                    self.visit(stmt)
        finally:
            for stmt in node.always_body:
                self.visit(stmt)
    def visit_UnaryOp(self, node: UnaryOp):
        val = self.visit(node.right)
        if node.op == 'not':
            return not val
        if node.op == '-':
            return -val
        raise Exception(f"Unknown unary operator: {node.op}")
    def visit_Throw(self, node: Throw):
        """
        -----Purpose: Throws a runtime error with a custom message.
        """
        message = self.visit(node.message)
        raise RuntimeError(message)
    def visit_FunctionDef(self, node: FunctionDef):
        """
        -----Purpose: Stores a function definition in the interpreter state.
        """
        self.functions[node.name] = node
    def visit_Return(self, node: Return):
        """
        -----Purpose: Evaluates a return expression and raises a ReturnException.
        """
        value = self.visit(node.value)
        raise ReturnException(value)
    def _call_function_def(self, func_def: FunctionDef, args: List[Node]):
        if len(args) > len(func_def.args):
             raise TypeError(f"Function '{func_def.name}' expects max {len(func_def.args)} arguments, got {len(args)}")
        old_env = self.current_env
        new_env = Environment(parent=self.global_env)
        for i, (arg_name, default_node, type_hint) in enumerate(func_def.args):
            if i < len(args):
                val = self.visit(args[i])
            elif default_node is not None:
                val = self.visit(default_node)
            else:
                raise TypeError(f"Missing required argument '{arg_name}' for function '{func_def.name}'")
            if type_hint:
                self._check_type(arg_name, val, type_hint)
            new_env.set(arg_name, val)
        self.current_env = new_env
        ret_val = None
        try:
            for stmt in func_def.body:
                val = self.visit(stmt)
                ret_val = val
        except ReturnException as e:
            ret_val = e.value
        except Exception as e:
            self.current_env = old_env
            raise e
        finally:
            self.current_env = old_env
            
        return ret_val
    def visit_Call(self, node: Call):
        kwargs = {}
        if node.kwargs:
            for k, v in node.kwargs:
                kwargs[k] = self.visit(v)
        if node.name in self.builtins:
             args = [self.visit(a) for a in node.args]
             if kwargs:
                 result = self.builtins[node.name](*args, **kwargs)
             else:
                 result = self.builtins[node.name](*args)
             if isinstance(result, Tag):
                 if node.body:
                     self.web.push(result)
                     try:
                         for stmt in node.body:
                             res = self.visit(stmt)
                             if res is not None and (isinstance(res, str) or isinstance(res, Tag)):
                                 self.web.add_text(res)
                     finally:
                         self.web.pop()
             return result
        try:
            func = self.current_env.get(node.name)
            if callable(func):
                args = [self.visit(a) for a in node.args]
                if kwargs:
                    return func(*args, **kwargs)
                return func(*args)
            curr_obj = func
            is_valid_type = isinstance(
                curr_obj, (list, dict, str, Instance)
            )
            if is_valid_type:
                valid_chain = True
                for arg_node in node.args:
                    val = self.visit(arg_node)
                    if isinstance(val, list) and len(val) == 1:
                        idx = val[0]
                        try:
                            curr_obj = curr_obj[idx]
                        except (IndexError, KeyError) as e:
                            raise RuntimeError(f"Index/Key error: {e}")
                        except TypeError:
                             valid_chain = False
                             break
                    else:
                        valid_chain = False
                        break
                if valid_chain:
                    return curr_obj
                pass
        except NameError:
            pass
        if node.name in self.classes:
            from .ast_nodes import Instantiation
            inst = Instantiation(var_name=None, class_name=node.name, args=node.args, kwargs=node.kwargs)
            inst.line = node.line
            inst.col = node.col
            return self.visit_Instantiation(inst)

        if node.name not in self.functions:
            msg = (
                f"Function '{node.name}' not defined "
                "(and not a variable)."
            )
            raise NameError(msg)
        func_def = self.functions[node.name]
        return self._call_function_def(func_def, node.args)
    def visit_ClassDef(self, node: ClassDef):
        """
        -----Purpose: Stores a class definition in the interpreter state.
        """
        self.classes[node.name] = node
    def visit_Instantiation(self, node: Instantiation):
        """
        -----Purpose: Creates a new instance of a structure/class.
        """
        if node.class_name not in self.classes:
            raise NameError(f"Class '{node.class_name}' not defined.")
        class_def = self.classes[node.class_name]
        all_properties = self._get_class_properties(class_def)
        required_count = 0
        for name, default_val in all_properties:
            if default_val is None:
                required_count += 1
        if len(node.args) < required_count:
             msg = (
                 f"Structure '{node.class_name}' expects at "
                 f"least {required_count} args, got {len(node.args)}"
             )
             raise TypeError(msg)
        instance = Instance(class_def)
        for i, (prop_name, default_val) in enumerate(all_properties):
            val = None
            if i < len(node.args):
                val = self.visit(node.args[i])
            elif default_val is not None:
                val = self.visit(default_val)
            else:
                msg = (
                    f"Missing argument for property '{prop_name}' "
                    f"in '{node.class_name}'"
                )
                raise TypeError(msg)
            instance.data[prop_name] = val
        self.current_env.set(node.var_name, instance)
        return instance
    def visit_MethodCall(self, node: MethodCall):
        """
        -----Purpose: Executes a method call on a structure instance.
        """
        instance = self.current_env.get(node.instance_name)
        if isinstance(instance, dict):
            if node.method_name not in instance:
                msg = (
                    f"Module '{node.instance_name}' has no "
                    f"method '{node.method_name}'"
                )
                raise AttributeError(msg)
            method = instance[node.method_name]
            if isinstance(method, FunctionDef):
                 return self._call_function_def(method, node.args)
            elif callable(method):
                args = [self.visit(a) for a in node.args]
                try:
                    return method(*args)
                except Exception as e:
                    raise RuntimeError(f"Error calling '{node.instance_name}.{node.method_name}': {e}")
            elif isinstance(method, (dict, list, str)):
                 curr_obj = method
                 valid_chain = True
                 for arg_node in node.args:
                    val = self.visit(arg_node)
                    if isinstance(val, list) and len(val) == 1:
                        idx = val[0]
                        try:
                            curr_obj = curr_obj[idx]
                        except (IndexError, KeyError) as e:
                            raise RuntimeError(f"Index/Key error: {e}")
                        except TypeError:
                             valid_chain = False
                             break
                    else:
                        valid_chain = False
                        break
                 if valid_chain:
                     return curr_obj
                 msg = (
                     f"Property '{node.method_name}' is not callable "
                     "and index access failed."
                 )
                 raise TypeError(msg)
            else:
                 raise TypeError(f"Property '{node.method_name}' is not callable.")
        if hasattr(instance, node.method_name) and callable(getattr(instance, node.method_name)):
             method = getattr(instance, node.method_name)
             args = [self.visit(a) for a in node.args]
             return method(*args)
        if not isinstance(instance, Instance):
            raise TypeError(f"'{node.instance_name}' is not a structure instance (and has no native method '{node.method_name}').")
        method_node = self._find_method(instance.class_def, node.method_name)
        if not method_node:
            raise AttributeError(f"Structure '{instance.class_def.name}' has no method '{node.method_name}'")
        old_env = self.current_env
        new_env = Environment(parent=self.global_env)
        for k, v in instance.data.items():
            new_env.set(k, v)
        if len(node.args) > len(method_node.args):
             raise TypeError(f"Method '{node.method_name}' expects max {len(method_node.args)} arguments.")
        for i, (arg_name, default_node, type_hint) in enumerate(method_node.args):
             if i < len(node.args):
                 val = self.visit(node.args[i])
             elif default_node is not None:
                 val = self.visit(default_node)
             else:
                 raise TypeError(f"Missing required argument '{arg_name}' for method '{node.method_name}'")
             new_env.set(arg_name, val)
        self.current_env = new_env
        ret_val = None
        try:
            for stmt in method_node.body:
                self.visit(stmt)
        except ReturnException as e:
            ret_val = e.value
        finally:
            for k in instance.data.keys():
                if k in new_env.variables:
                    instance.data[k] = new_env.variables[k]
            self.current_env = old_env
        return ret_val
    def visit_PropertyAccess(self, node: PropertyAccess):
        """
        -----Purpose: Evaluates an access to an object or dictionary property.
        """
        instance = self.current_env.get(node.instance_name)
        if isinstance(instance, Instance):
            if node.property_name not in instance.data:
                 raise AttributeError(f"Structure '{instance.class_def.name}' has no property '{node.property_name}'")
            return instance.data[node.property_name]
        elif isinstance(instance, dict):
             if node.property_name in instance:
                 return instance[node.property_name]
             raise AttributeError(f"Dictionary has no key '{node.property_name}'")
        elif isinstance(instance, list):
             if node.property_name == 'length':
                 return len(instance)
        elif isinstance(instance, str):
             if node.property_name == 'length':
                 return len(instance)
        if hasattr(instance, node.property_name):
             return getattr(instance, node.property_name)
        msg = (
            f"Object '{node.instance_name}' (type "
            f"{type(instance).__name__}) has no property "
            f"'{node.property_name}'"
        )
        raise TypeError(msg)
    def visit_Import(self, node: Import):
        """
        -----Purpose: Handles importing of ShellLite or Python modules.
        """
        if node.path in self.std_modules:
            self.current_env.set(node.path, self.std_modules[node.path])
            return
        import importlib
        import os
        target_path = None
        if os.path.exists(node.path):
             target_path = node.path
        else:
             home = os.path.expanduser("~")
             global_path = os.path.join(
                 home, ".shell_lite", "modules", node.path
             )
             if os.path.exists(global_path):
                 target_path = global_path
             else:
                 if not node.path.endswith('.shl'):
                     global_path_ext = global_path + ".shl"
                     if os.path.exists(global_path_ext):
                         target_path = global_path_ext
        if target_path:
            if os.path.isdir(target_path):
                 main_shl = os.path.join(target_path, "main.shl")
                 pkg_shl = os.path.join(target_path, f"{os.path.basename(target_path)}.shl")
                 if os.path.exists(main_shl):
                     target_path = main_shl
                 elif os.path.exists(pkg_shl):
                     target_path = pkg_shl
                 else:
                      raise FileNotFoundError(f"Package '{node.path}' is a folder but has no 'main.shl' or '{os.path.basename(target_path)}.shl'.")
            try:
                with open(target_path, 'r', encoding='utf-8') as f:
                    code = f.read()
            except FileNotFoundError:
                raise FileNotFoundError(f"Could not find imported file: {node.path}")
            from .lexer import Lexer
            from .parser_gbp import GeometricBindingParser
            lexer = Lexer(code)
            tokens = lexer.tokenize()
            parser = GeometricBindingParser(tokens)
            statements = parser.parse()
            for stmt in statements:
                self.visit(stmt)
            return
        try:
            py_module = importlib.import_module(node.path)
            # Wrap in Namespace for clean access
            members = {k: getattr(py_module, k) for k in dir(py_module) if not k.startswith('_')}
            ns = Namespace(node.path, members)
            self.current_env.set(node.path, ns)
            return
        except ImportError:
            pass
        msg = (
            f"Could not find module '{node.path}'. Searched:\n"
            " - ShellLite Local/Global\n"
            " - Python Site-Packages (The Bridge)"
        )
        raise FileNotFoundError(msg)
    def _get_class_properties(self, class_def: ClassDef) -> List[tuple[str, Optional[Node]]]:
        """
        -----Purpose: Recursive helper to retrieve all properties of a class.
        """
        if not hasattr(class_def, 'properties'): return []
        props = []
        for p in class_def.properties:
            if isinstance(p, tuple):
                props.append(p)
            else:
                props.append((p, None))
        if class_def.parent:
            if class_def.parent not in self.classes:
                raise NameError(f"Parent class '{class_def.parent}' not defined.")
            parent_def = self.classes[class_def.parent]
            return self._get_class_properties(parent_def) + props
        return props
    def _find_method(self, class_def: ClassDef, method_name: str) -> Optional[FunctionDef]:
        """
        -----Purpose: Recursive helper to find a method in a class hierarchy.
        """
        for m in class_def.methods:
            if m.name == method_name:
                return m
        if class_def.parent:
             if class_def.parent not in self.classes:
                raise NameError(f"Parent class '{class_def.parent}' not defined.")
             parent_def = self.classes[class_def.parent]
             return self._find_method(parent_def, method_name)
        return None
    def builtin_run(self, cmd):
        if self.safe_mode: raise PermissionError("System execution is disabled in Safe Mode")
        return subprocess.check_output(cmd, shell=True).decode()
    def builtin_read(self, path):
        if self.safe_mode: raise PermissionError("File reading is disabled in Safe Mode")
        with open(path, 'r') as f: return f.read()
    def builtin_write(self, path, content):
        if self.safe_mode: raise PermissionError("File writing is disabled in Safe Mode")
        with open(path, 'w') as f: f.write(content)
    def builtin_json_parse(self, json_str):
        """
        -----Purpose: Parses a JSON string into a ShellLite object/list.
        """
        try:
            return json.loads(json_str)
        except Exception as e:
            raise RuntimeError(f"Invalid JSON: {e}")
    def builtin_json_stringify(self, obj):
        """
        -----Purpose: Converts a ShellLite object/list into a JSON string.
        """
        try:
            if isinstance(obj, Instance):
                return json.dumps(obj.data)
            return json.dumps(obj)
        except Exception as e:
            raise RuntimeError(f"JSON stringify failed: {e}")
    def builtin_http_get(self, url, headers=None):
        """
        -----Purpose: Performs a synchronous HTTP GET request with optional headers.
        """
        try:
            if isinstance(headers, Instance):
                headers = headers.data
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req) as response:
                return response.read().decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"HTTP GET failed for '{url}': {e}")
    def builtin_http_post(self, url, data_dict, headers=None):
        """
        -----Purpose: Performs a synchronous HTTP POST request with JSON data and optional headers.
        """
        try:
            if isinstance(headers, Instance):
                headers = headers.data
            if isinstance(data_dict, Instance):
                data_dict = data_dict.data
            data = json.dumps(data_dict).encode('utf-8')
            all_headers = {'Content-Type': 'application/json'}
            if headers:
                all_headers.update(headers)
            req = urllib.request.Request(url, data=data, headers=all_headers)
            with urllib.request.urlopen(req) as response:
                 return response.read().decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"HTTP POST failed for '{url}': {e}")
    def visit_Lambda(self, node: Lambda):
        """
        -----Purpose: Evaluates a lambda expression into a callable.
        """
        return LambdaFunction(node.params, node.body, self)
    def visit_Ternary(self, node: Ternary):
        """
        -----Purpose: Evaluates a ternary conditional expression.
        """
        condition = self.visit(node.condition)
        if condition:
            return self.visit(node.true_expr)
        else:
            return self.visit(node.false_expr)
    def visit_ListComprehension(self, node: ListComprehension):
        """
        -----Purpose: Evaluates a list comprehension expression.
        """
        iterable = self.visit(node.iterable)
        if not hasattr(iterable, '__iter__'):
            msg = f"Cannot iterate over {type(iterable).__name__}"
            raise TypeError(msg)
        result = []
        old_env = self.current_env
        new_env = Environment(parent=self.current_env)
        self.current_env = new_env
        try:
            for item in iterable:
                new_env.set(node.var_name, item)
                include = True
                if node.condition:
                    cond_val = self.visit(node.condition)
                    if callable(cond_val):
                        include = bool(cond_val(item))
                    else:
                        include = bool(cond_val)
                
                if include:
                    result.append(self.visit(node.expr))
        finally:
            self.current_env = old_env
        return result
    def visit_Spread(self, node: Spread):
        """
        -----Purpose: Returns the value of a spread operation target.
        """
        return self.visit(node.value)
    def visit_Alert(self, node: Alert):
        """
        -----Purpose: Displays a GUI alert message box (or falls back to print).
        """
        msg = self.visit(node.message)
        if _HAS_TK:
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            messagebox.showinfo("Alert", str(msg))
            root.destroy()
        else:
            print(f"[Alert] {msg}")
    def visit_Prompt(self, node: Prompt):
        """
        -----Purpose: Displays a GUI text input dialog (or falls back to input()).
        """
        prompt = self.visit(node.prompt)
        if _HAS_TK:
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            val = simpledialog.askstring("Input", str(prompt))
            root.destroy()
            return val if val is not None else ""
        else:
            return input(str(prompt) + " ")
    def visit_Confirm(self, node: Confirm):
        """
        -----Purpose: Displays a GUI yes/no confirmation dialog (or falls back to input()).
        """
        prompt = self.visit(node.prompt)
        if _HAS_TK:
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            val = messagebox.askyesno("Confirm", str(prompt))
            root.destroy()
            return val
        else:
            return input(str(prompt) + " (yes/no) ").strip().lower() in ('yes', 'y', '1', 'true')
    def visit_Spawn(self, node: Spawn):
        """
        -----Purpose: Spawns a background task using the shared thread pool.
        """
        return self._shared_executor.submit(self.visit, node.call)
    def visit_Await(self, node: Await):
        """
        -----Purpose: Awaits the result of an asynchronous task.
        """
        task = self.visit(node.task)
        if isinstance(task, concurrent.futures.Future):
            return task.result()
        return task # Graceful fallback for non-futures
    def visit_Regex(self, node: Regex):
        """
        -----Purpose: Compiles and returns a regular expression object.
        """
        return re.compile(node.pattern)
    def visit_FileWatcher(self, node: FileWatcher):
        """
        -----Purpose: Monitors a file for changes and executes a block.
        """
        path = self.visit(node.path)
        if not os.path.exists(path):
            print(f"Warning: Watching non-existent file {path}")
            last_mtime = 0
        else:
            last_mtime = os.path.getmtime(path)
        try:
            while True:
                current_exists = os.path.exists(path)
                if current_exists:
                    current_mtime = os.path.getmtime(path)
                    if current_mtime != last_mtime:
                        last_mtime = current_mtime
                        for stmt in node.body:
                            self.visit(stmt)
                time.sleep(1)
        except StopException:
            pass
        except ReturnException:
            raise
    def _check_type(self, arg_name, val, type_hint):
        if type_hint == 'int' and not isinstance(val, int):
            raise TypeError(f"Argument '{arg_name}' expects int, got {type(val).__name__}")
        elif type_hint == 'str' and not isinstance(val, str):
            raise TypeError(f"Argument '{arg_name}' expects str, got {type(val).__name__}")
        elif type_hint == 'bool' and not isinstance(val, bool):
             raise TypeError(f"Argument '{arg_name}' expects bool, got {type(val).__name__}")
        elif type_hint == 'float' and not isinstance(val, (float, int)):
             raise TypeError(f"Argument '{arg_name}' expects float, got {type(val).__name__}")
        elif type_hint == 'list' and not isinstance(val, list):
             raise TypeError(f"Argument '{arg_name}' expects list, got {type(val).__name__}")
    def visit_ConstAssign(self, node: ConstAssign):
        value = self.visit(node.value)
        self.current_env.set_const(node.name, value)
        return value
    def visit_ForIn(self, node: ForIn):
        """
        -----Purpose: Evaluates a for in loop over an iterable.
        """
        iterable = self.visit(node.iterable)
        if not hasattr(iterable, '__iter__'):
            raise TypeError(f"Cannot iterate over {type(iterable).__name__}")
        for item in iterable:
            self.current_env.set(node.var_name, item)
            try:
                for stmt in node.body:
                    self.visit(stmt)
            except StopException:
                break
            except SkipException:
                continue
            except ReturnException:
                raise
            except Exception as e:
                raise e
    def visit_IndexAccess(self, node: IndexAccess):
        """
        -----Purpose: Evaluates an index or key access on a collection.
        """
        obj = self.visit(node.obj)
        index = self.visit(node.index)
        if isinstance(obj, list):
            if not isinstance(index, int):
                msg = (
                    f"List indices must be integers, "
                    f"got {type(index).__name__}"
                )
                raise TypeError(msg)
            return obj[index]
        elif isinstance(obj, dict):
            return obj[index]
        elif isinstance(obj, str):
            if not isinstance(index, int):
                msg = (
                    f"String indices must be integers, "
                    f"got {type(index).__name__}"
                )
                raise TypeError(msg)
            return obj[index]
        else:
            msg = f"'{type(obj).__name__}' object is not subscriptable"
            raise TypeError(msg)
    def visit_Stop(self, node: Stop):
        """
        -----Purpose: Raises a StopException to break out of a loop.
        """
        raise StopException()
    def visit_Skip(self, node: Skip):
        """
        -----Purpose: Raises a SkipException to continue a loop.
        """
        raise SkipException()
    def visit_Dictionary(self, node: Dictionary):
        """
        -----Purpose: Evaluates a dictionary literal into a Python dictionary.
        """
        result = {}
        for key_node, val_node in node.pairs:
            key = self.visit(key_node)
            val = self.visit(val_node)
            result[key] = val
        return result
    def _builtin_split(self, s, delimiter=None):
        if delimiter == "":
            return list(s)
        return s.split(delimiter)
    def visit_PythonImport(self, node: PythonImport):
        name = node.module_name
        if name in self.std_modules:
            alias = node.alias or name
            self.current_env.variables[alias] = self.std_modules[name]
            return
        try:
            mod = importlib.import_module(name)
            alias = node.alias or name
            self.current_env.variables[alias] = mod
        except ImportError:
            raise ImportError(f"Cannot find module '{name}'")
    def visit_FromImport(self, node: FromImport):
        """
        -----Purpose: Imports specific attributes from a Python module.
        """
        try:
            mod = importlib.import_module(node.module_name)
            for name, alias in node.names:
                if not hasattr(mod, name):
                    msg = (
                        f"Module '{node.module_name}' has no "
                        f"attribute '{name}'"
                    )
                    raise AttributeError(msg)
                val = getattr(mod, name)
                target_name = alias if alias else name
                self.global_env.set(target_name, val)
        except ImportError as e:
            msg = (
                f"Could not import python module '{node.module_name}': {e}"
            )
            raise RuntimeError(msg)
    def visit_Throw(self, node: Throw):
        """
        -----Purpose: Throws a ShellLite-specific runtime error.
        """
        message = self.visit(node.message)
        raise ShellLiteError(str(message))
    def visit_Unless(self, node: Unless):
        """
        -----Purpose: Evaluates an unless block (inverse of if).
        """
        condition = self.visit(node.condition)
        if not condition:
            for stmt in node.body:
                self.visit(stmt)
        elif node.else_body:
            for stmt in node.else_body:
                self.visit(stmt)
    def visit_Until(self, node: Until):
        """
        -----Purpose: Evaluates an until loop (inverse of while).
        """
        while not self.visit(node.condition):
            try:
                for stmt in node.body:
                    self.visit(stmt)
            except StopException:
                break
            except SkipException:
                continue
            except ReturnException:
                raise
    def visit_Repeat(self, node: Repeat):
        """
        -----Purpose: Evaluates a repeat loop with automatic index variable.
        """
        count = self.visit(node.count)
        if not isinstance(count, int):
            msg = (
                f"repeat count must be an integer, "
                f"got {type(count).__name__}"
            )
            raise TypeError(msg)
        old_env = self.current_env
        self.current_env = Environment(parent=self.current_env)
        try:
            for i in range(count):
                self.current_env.set('index', i)
                try:
                    for stmt in node.body:
                        self.visit(stmt)
                except StopException:
                    break
                except SkipException:
                    continue
        except ReturnException:
            raise
        finally:
            self.current_env = old_env
    def visit_When(self, node: When):
        """
        -----Purpose: Evaluates a pattern matching switch-like block.
        """
        value = self.visit(node.value)
        for match_val, body in node.cases:
            if self.visit(match_val) == value:
                for stmt in body:
                    self.visit(stmt)
                return
        if node.otherwise:
            for stmt in node.otherwise:
                self.visit(stmt)
    def visit_Execute(self, node: Execute):
        """
        -----Purpose: Runtime execution of code from a string.
        """
        code = self.visit(node.code)
        if not isinstance(code, str):
            msg = f"execute requires a string, got {type(code).__name__}"
            raise TypeError(msg)
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = GeometricBindingParser(tokens)
        statements = parser.parse()
        result = None
        for stmt in statements:
            result = self.visit(stmt)
        self.current_env.set('__exec_result__', result)
        return result
    def visit_ImportAs(self, node: ImportAs):
        if node.path in self.std_modules:
            self.current_env.set(node.alias, self.std_modules[node.path])
            return
        old_funcs_keys = set(self.functions.keys())
        module_env = Environment(parent=self.global_env)
        old_env = self.current_env
        self.current_env = module_env
        module_env = Environment(parent=self.global_env)
        old_env = self.current_env
        self.current_env = module_env
        if os.path.exists(node.path):
             target_path = node.path
        else:
             home = os.path.expanduser("~")
             global_path = os.path.join(home, ".shell_lite", "modules", node.path)
             if os.path.exists(global_path):
                 target_path = global_path
             else:
                  if not node.path.endswith('.shl'):
                       global_path_ext = global_path + ".shl"
                       if os.path.exists(global_path_ext):
                            target_path = global_path_ext
                       else:
                            self.current_env = old_env
                            raise FileNotFoundError(f"Could not find imported file: {node.path} (searched local and global modules)")
                  else:
                       self.current_env = old_env
                       raise FileNotFoundError(f"Could not find imported file: {node.path} (searched local and global modules)")
        if os.path.isdir(target_path):
             main_shl = os.path.join(target_path, "main.shl")
             pkg_shl = os.path.join(target_path, f"{os.path.basename(target_path)}.shl")
             if os.path.exists(main_shl):
                 target_path = main_shl
             elif os.path.exists(pkg_shl):
                 target_path = pkg_shl
             else:
                  self.current_env = old_env
                  raise FileNotFoundError(f"Package '{node.path}' is a folder but has no 'main.shl' or '{os.path.basename(target_path)}.shl'.")
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                code = f.read()
            from .lexer import Lexer
            from .parser_gbp import GeometricBindingParser
            lexer = Lexer(code)
            tokens = lexer.tokenize()
            parser = GeometricBindingParser(tokens)
            statements = parser.parse()
            for stmt in statements:
                self.visit(stmt)
            module_exports = {}
            module_exports.update(module_env.variables)
            current_funcs_keys = set(self.functions.keys())
            new_funcs = current_funcs_keys - old_funcs_keys
            for fname in new_funcs:
                func_node = self.functions[fname]
                module_exports[fname] = func_node
                del self.functions[fname]
            self.current_env = old_env
            self.current_env.set(node.alias, module_exports)
        except Exception as e:
            self.current_env = old_env
            raise RuntimeError(f"Failed to import '{node.path}': {e}")
    def visit_Forever(self, node: Forever):
        while True:
            try:
                for stmt in node.body:
                    self.visit(stmt)
            except StopException:
                break
            except SkipException:
                continue
            except ReturnException:
                raise
    def visit_Exit(self, node: Exit):
        code = 0
        if node.code:
            code = self.visit(node.code)
            sys.exit(int(code))
        sys.exit(0)
    def visit_App(self, node: App):
        """
        -----Purpose: Initializes and runs a Tkinter-based GUI application.
        """
        if not _HAS_TK:
            print("[App] GUI apps require tkinter. Install python3-tk on Linux (sudo apt install python3-tk).")
            return
        root = tk.Tk()
        root.title(node.title)
        root.geometry(f"{node.width}x{node.height}")
        self.ui_parent_stack = [root]
        def ui_alert(msg):
            messagebox.showinfo("Message", str(msg))
        self.current_env.set("alert", ui_alert)
        try:
            for child in node.body:
                self.visit(child)
        finally:
            self.ui_parent_stack.pop()
        root.mainloop()
    def visit_Layout(self, node: Layout):
        """
        -----Purpose: Creates a UI layout frame and manages child placement.
        """
        parent_ctx = self.ui_parent_stack[-1]
        if isinstance(parent_ctx, tuple):
            parent = parent_ctx[0]
        else:
            parent = parent_ctx
        frame = tk.Frame(parent)
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.ui_parent_stack.append((frame, node.layout_type))
        try:
            for child in node.body:
                self.visit(child)
        finally:
            self.ui_parent_stack.pop()
    def visit_Widget(self, node: Widget):
        """
        -----Purpose: Creates and renders a UI widget (button, input, etc.).
        """
        if not _HAS_TK:
            return
        parent_ctx = self.ui_parent_stack[-1]
        if isinstance(parent_ctx, tuple):
            parent, layout_mode = parent_ctx
        else:
            parent = parent_ctx
            layout_mode = 'column'
        widget = None
        if node.widget_type == 'button':
            def on_click():
                if node.event_handler:
                    try:
                        for stmt in node.event_handler:
                            self.visit(stmt)
                    except Exception as e:
                        messagebox.showerror("Error", str(e))
            widget = tk.Button(parent, text=node.label, command=on_click)
        elif node.widget_type == 'input':
            lbl = tk.Label(parent, text=node.label)
            if layout_mode == 'column':
                pack_opts = {'side': tk.TOP, 'anchor': 'w'}
            else:
                pack_opts = {'side': tk.LEFT}
            lbl.pack(**pack_opts)
            widget = tk.Entry(parent)
            if node.var_name:
                class InputWrapper:
                    def __init__(self, w): self.w = w
                    @property
                    def value(self): return self.w.get()
                    @property
                    def text(self): return self.w.get()
                self.current_env.set(node.var_name, InputWrapper(widget))
        elif node.widget_type == 'heading':
            font_cfg = ("Helvetica", 16, "bold")
            widget = tk.Label(parent, text=node.label, font=font_cfg)
        elif node.widget_type == 'text':
            widget = tk.Label(parent, text=node.label)
        if widget:
            if layout_mode == 'column':
                widget.pack(side=tk.TOP, pady=5, fill=tk.X)
            else:
                widget.pack(side=tk.LEFT, padx=5)
    def visit_Make(self, node: Make):
        """
        -----Purpose: Creates an instance of a structure (alternative syntax).
        """
        if node.class_name not in self.classes:
            raise NameError(f"Thing '{node.class_name}' not defined.")
        class_def = self.classes[node.class_name]
        props = self._get_class_properties(class_def)
        required_count = 0
        for name, default_val in props:
            if default_val is None:
                required_count += 1
        if len(node.args) < required_count:
             msg = (
                 f"Thing '{node.class_name}' expects at "
                 f"least {required_count} values, got {len(node.args)}"
             )
             raise TypeError(msg)
        instance = Instance(class_def)
        for i, (prop_name, default_val) in enumerate(props):
            val = None
            if i < len(node.args):
                val = self.visit(node.args[i])
            elif default_val is not None:
                val = self.visit(default_val)
            else:
                msg = (
                    f"Missing argument for property '{prop_name}' "
                    f"in '{node.class_name}'"
                )
                raise TypeError(msg)
            instance.data[prop_name] = val
        return instance
    def visit_Convert(self, node: Convert):
        """
        -----Purpose: Converts data between different formats (e.g., JSON).
        """
        val = self.visit(node.expression)
        if node.target_format.lower() == 'json':
             if isinstance(val, str):
                 try:
                     return json.loads(val)
                 except:
                     return json.dumps(val)
             else:
                 if isinstance(val, Instance):
                     return json.dumps(val.data)
                 return json.dumps(val)
        msg = f"Unknown conversion format: {node.target_format}"
        raise ValueError(msg)
    def visit_ProgressLoop(self, node: ProgressLoop):
        """
        -----Purpose: Displays a progress bar for a loop execution.
        """
        loop = node.loop_node
        if isinstance(loop, Repeat):
             count = self.visit(loop.count)
             if not isinstance(count, int): count = 0
             print("Progress: [                    ] 0%", end='\r')
             for i in range(count):
                 percent = int((i / count) * 100)
                 bar = '=' * int(percent / 5)
                 print(f"Progress: [{bar:<20}] {percent}%", end='\r')
                 try:
                     for stmt in loop.body:
                         self.visit(stmt)
                 except: 
                     pass
             print(f"Progress: [{'='*20}] 100%           ")
        elif isinstance(loop, For):
             count = self.visit(loop.count)
             for i in range(count):
                 percent = int((i / count) * 100)
                 bar = '=' * int(percent / 5)
                 print(f"Progress: [{bar:<20}] {percent}%", end='\r')
                 try:
                    for stmt in loop.body:
                        self.visit(stmt)
                 except: 
                     pass
             print(f"Progress: [{'='*20}] 100%           ")
        elif isinstance(loop, ForIn):
            iterable = self.visit(loop.iterable)
            total = len(iterable) if hasattr(iterable, '__len__') else 0
            i = 0
            for item in iterable:
                if total > 0:
                    percent = int((i / total) * 100)
                    bar = '=' * int(percent / 5)
                    print(f"Progress: [{bar:<20}] {percent}%", end='\r')
                self.current_env.set(loop.var_name, item)
                try:
                    for stmt in loop.body:
                        self.visit(stmt)
                except: 
                    pass
                i += 1
            if total > 0:
                print(f"Progress: [{'='*20}] 100%           ")
    def visit_DatabaseOp(self, node: DatabaseOp):
        """
        -----Purpose: Performs database operations with Safe Mode checks.
        """
        if self.safe_mode: raise PermissionError("Database operations are disabled in Safe Mode")
        if node.op == 'open':
            path = self.visit(node.args[0])
            self.db_conn = sqlite3.connect(path, check_same_thread=False)
            self.db_conn.row_factory = sqlite3.Row
            return True
        elif node.op == 'exec':
            if not self.db_conn: raise RuntimeError("Database not open")
            sql = self.visit(node.args[0])
            params = [self.visit(arg) for arg in node.args[1:]]
            cursor = self.db_conn.cursor()
            cursor.execute(sql, params)
            self.db_conn.commit()
            return cursor.lastrowid
        elif node.op == 'query':
            if not self.db_conn: raise RuntimeError("Database not open")
            sql = self.visit(node.args[0])
            params = [self.visit(arg) for arg in node.args[1:]]
            cursor = self.db_conn.cursor()
            cursor.execute(sql, params)
            desc = cursor.description
            columns = [d[0] for d in desc] if desc else []
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        elif node.op == 'close':
            if self.db_conn:
                self.db_conn.close()
                self.db_conn = None
            return True

    def visit_ModelDef(self, node: ModelDef):
        self.classes[node.name] = node
        return None

    def visit_CreateTable(self, node: CreateTable):
        if not self.db_conn: raise RuntimeError("Database not open")
        model = self.classes.get(node.model_name)
        if not model: raise NameError(f"Model '{node.model_name}' not defined")
        fields = []
        for f_name, f_type in model.fields:
            sql_type = "TEXT"
            if f_type == "int": sql_type = "INTEGER"
            elif f_type == "float": sql_type = "REAL"
            fields.append(f"{f_name} {sql_type}")
        sql = f"CREATE TABLE IF NOT EXISTS {node.model_name} ({', '.join(fields)})"
        self.db_conn.execute(sql)
        self.db_conn.commit()
        return True

    def visit_InsertRecord(self, node: InsertRecord):
        if not self.db_conn: raise RuntimeError("Database not open")
        placeholders = ", ".join(["?"] * len(node.values))
        cols = ", ".join([v[0] for v in node.values])
        vals = [self.visit(v[1]) for v in node.values]
        sql = f"INSERT INTO {node.model_name} ({cols}) VALUES ({placeholders})"
        cursor = self.db_conn.cursor()
        cursor.execute(sql, vals)
        self.db_conn.commit()
        return cursor.lastrowid

    def visit_FindRecords(self, node: FindRecords):
        if not self.db_conn: raise RuntimeError("Database not open")
        base = "SELECT COUNT(*)" if node.is_count else "SELECT *"
        sql = f"{base} FROM {node.model_name}"
        params = []
        if node.conditions:
            conds = []
            for col, op, val in node.conditions:
                conds.append(f"{col} {op} ?")
                params.append(self.visit(val))
            sql += " WHERE " + " AND ".join(conds)
        
        cursor = self.db_conn.cursor()
        cursor.execute(sql, params)
        if node.is_count:
            res = cursor.fetchone()
            return res[0] if res else 0
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def visit_Parallel(self, node: Parallel):
        """
        -----Purpose: Executes body statements concurrently using the shared executor.
        """
        futures = []
        for stmt in node.body:
            futures.append(self._shared_executor.submit(self.visit, stmt))
        return futures

    def visit_Gather(self, node: Gather):
        """
        -----Purpose: Waits for a list of futures to complete and returns results.
        """
        futures = self.visit(node.tasks)
        if not isinstance(futures, list):
            futures = [futures]
        
        results = []
        for f in futures:
            if isinstance(f, concurrent.futures.Future):
                results.append(f.result())
            else:
                results.append(f)
        return results

    def visit_Lock(self, node: Lock):
        """
        -----Purpose: Acquires a named global lock for the duration of the block.
        """
        if node.name not in self._named_locks:
            self._named_locks[node.name] = threading.Lock()
        
        with self._named_locks[node.name]:
            # Use the newly defined visit_statement_list
            return self.visit_statement_list(node.body)

    def visit_Channel(self, node: Channel):
        """
        -----Purpose: Creates a new thread-safe queue.
        """
        return queue.Queue()

    def visit_Send(self, node: Send):
        """
        -----Purpose: Pushes a value into a channel (queue).
        """
        q = self.visit(node.channel)
        val = self.visit(node.value)
        if isinstance(q, queue.Queue):
            q.put(val)
        return val

    def visit_Receive(self, node: Receive):
        """
        -----Purpose: Pulls a value from a channel (blocking).
        """
        q = self.visit(node.channel)
        if isinstance(q, queue.Queue):
            return q.get()
        return None

    def visit_ModelDef(self, node: ModelDef):
        """
        -----Purpose: Registers a model definition.
        """
        self.models[node.name] = node
        return node

    def visit_CreateTable(self, node: CreateTable):
        """
        -----Purpose: Generates and executes SQL to create a table from a model.
        """
        model = self.models.get(node.model_name)
        if not model:
            raise RuntimeError(f"Model '{node.model_name}' not defined.")
        
        field_defs = []
        for name, ftype in model.fields:
            sql_type = "TEXT"
            if ftype in ('int', 'integer'): sql_type = "INTEGER"
            elif ftype in ('float', 'number'): sql_type = "REAL"
            field_defs.append(f"{name} {sql_type}")
        
        sql = f"CREATE TABLE IF NOT EXISTS {node.model_name} ({', '.join(field_defs)})"
        return self.visit(DatabaseOp('exec', [String(sql)]))

    def visit_InsertRecord(self, node: InsertRecord):
        """
        -----Purpose: Inserts a record into a model-backed table using parameterized queries.
        """
        if not self.db_conn: raise RuntimeError("Database not open")
        fields = [v[0] for v in node.values]
        vals = [self.visit(v[1]) for v in node.values]
        placeholders = ", ".join(["?"] * len(vals))
        
        sql = f"INSERT INTO {node.model_name} ({', '.join(fields)}) VALUES ({placeholders})"
        cursor = self.db_conn.cursor()
        cursor.execute(sql, vals)
        self.db_conn.commit()
        return cursor.lastrowid

    def visit_FindRecords(self, node: FindRecords):
        """
        -----Purpose: Executes a 'find' ORM query, optionally performing a COUNT.
        """
        table_name = node.model_name
        sql = f"SELECT {'COUNT(*)' if node.is_count else '*'} FROM {table_name}"
        params = []
        if node.conditions:
            where_clauses = []
            for field, op_name, val_node in node.conditions:
                val = self.visit(val_node)
                where_clauses.append(f"{field} {op_name} ?")
                params.append(val)
            sql += " WHERE " + " AND ".join(where_clauses)
        
        if not self.db_conn:
             raise RuntimeError("Database not open")
        c = self.db_conn.cursor()
        c.execute(sql, params)
        if node.is_count:
            res = c.fetchone()
            if isinstance(res, dict): return list(res.values())[0]
            return res[0] if res else 0
        return c.fetchall()

    def visit_UpdateRecords(self, node: UpdateRecords):
        """
        -----Purpose: Updates records in a model-backed table.
        """
        set_strs = []
        for field, val_node in node.updates:
            val = self.visit(val_node)
            if isinstance(val, str): val = f"'{val}'"
            set_strs.append(f"{field} = {val}")
        
        sql = f"UPDATE {node.model_name} SET {', '.join(set_strs)}"
        if node.conditions:
            cond_strs = []
            for field, op, val_node in node.conditions:
                val = self.visit(val_node)
                if isinstance(val, str): val = f"'{val}'"
                cond_strs.append(f"{field} {op} {val}")
            sql += f" WHERE {' AND '.join(cond_strs)}"
            
        return self.visit(DatabaseOp('exec', [String(sql)]))

    def visit_DeleteRecords(self, node: DeleteRecords):
        """
        -----Purpose: Deletes records from a model-backed table.
        """
        sql = f"DELETE FROM {node.model_name}"
        if node.conditions:
            cond_strs = []
            for field, op, val_node in node.conditions:
                val = self.visit(val_node)
                if isinstance(val, str): val = f"'{val}'"
                cond_strs.append(f"{field} {op} {val}")
            sql += f" WHERE {' AND '.join(cond_strs)}"
            
        return self.visit(DatabaseOp('exec', [String(sql)]))
    def visit_ServeStatic(self, node: ServeStatic):
        """
        -----Purpose: Registers a folder to serve static files over HTTP.
        """
        folder = str(self.visit(node.folder))
        url_prefix = str(self.visit(node.url))
        if not url_prefix.startswith('/'):
            url_prefix = '/' + url_prefix
        if not os.path.isdir(folder):
            print(f"Warning: Static folder '{folder}' does not exist.")
        self.static_routes[url_prefix] = folder
        print(f"Serving static files from '{folder}' at '{url_prefix}'")
    def visit_Every(self, node: Every):
        """
        -----Purpose: Executes a block periodically at a given interval.
        """
        interval = self.visit(node.interval)
        if node.unit == 'minutes':
            interval *= 60
        try:
            while True:
                for stmt in node.body:
                    self.visit(stmt)
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
    def visit_After(self, node: After):
        """
        -----Purpose: Executes a block once after a given delay.
        """
        delay = self.visit(node.delay)
        if node.unit == 'minutes':
            delay *= 60
        time.sleep(delay)
        for stmt in node.body:
            self.visit(stmt)
    def visit_OnRequest(self, node: OnRequest):
        """
        -----Purpose: Registers an HTTP route handler with pattern matching.
        """
        path_str = self.visit(node.path)
        if path_str == '__middleware__':
            self.middleware_routes.append(node.body)
            return
        regex_pattern = "^" + path_str + "$"
        if ':' in path_str:
            pattern = re.sub(r':(\w+)', r'(?P<\1>[^/]+)', path_str)
            regex_pattern = "^" + pattern + "$"
        compiled = re.compile(regex_pattern)
        self.http_routes.append((path_str, compiled, node.body))
    def visit_Listen(self, node: Listen):
        """
        -----Purpose: Starts the built-in HTTP server on a specified port. 
        -----        Restricted in Safe Mode.
        """
        if self.safe_mode: raise PermissionError("Web server is disabled in Safe Mode")

        port_val = self.visit(node.port)
        interpreter_ref = self
        class ReusableHTTPServer(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True
            def handle_error(self, request, client_address):
                try:
                    _, exc, _ = sys.exc_info()
                    is_network_err = isinstance(
                        exc, (ConnectionResetError, BrokenPipeError)
                    )
                    if is_network_err:
                        return
                except:
                    pass
                super().handle_error(request, client_address)
        class ShellLiteHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args): pass
            def do_GET(self):
                self.handle_req()
            def do_POST(self):
                content_length = int(self.headers.get('Content-Length', 0))
                content_type = self.headers.get('Content-Type', '')
                post_data = self.rfile.read(content_length).decode('utf-8')
                params = {}
                json_data = None
                if 'application/json' in content_type:
                    try:
                        json_data = json.loads(post_data)
                    except:
                        pass
                else:
                    if post_data:
                        parsed = urllib.parse.parse_qs(post_data)
                        params = {k: v[0] for k, v in parsed.items()}
                self.handle_req(params, json_data)
            def do_HEAD(self):
                self.handle_req()
            def handle_req(self, post_params=None, json_data=None):
                try:
                    interpreter_ref.current_env = interpreter_ref.global_env
                    if post_params is None: post_params = {}
                    path = self.path
                    if '?' in path: path = path.split('?')[0]
                    req_obj = {
                        "method": self.command,
                        "path": path,
                        "params": post_params,
                        "form": post_params,
                        "json": json_data
                    }
                    interpreter_ref.global_env.set("request", req_obj)
                    interpreter_ref.global_env.set("REQUEST_METHOD", self.command)
                    for prefix, folder in interpreter_ref.static_routes.items():
                        if path.startswith(prefix):
                            clean_path = path[len(prefix):]
                            if clean_path.startswith('/'): clean_path = clean_path[1:]
                            if clean_path == '': clean_path = 'index.html'
                            file_path = os.path.join(folder, clean_path)
                            if os.path.exists(file_path) and os.path.isfile(file_path):
                                 self.send_response(200)
                                 ct = 'application/octet-stream'
                                 if file_path.endswith('.css'): ct = 'text/css'
                                 elif file_path.endswith('.html'): ct = 'text/html'
                                 elif file_path.endswith('.js'): ct = 'application/javascript'
                                 self.send_header('Content-Type', ct)
                                 self.end_headers()
                                 if self.command != 'HEAD':
                                     try:
                                         with open(file_path, 'rb') as f: self.wfile.write(f.read())
                                     except (BrokenPipeError, ConnectionResetError): pass
                                 return
                    matched_body = None
                    path_params = {}
                    for pattern, regex, body in interpreter_ref.http_routes:
                        match = regex.match(path)
                        if match:
                            matched_body = body
                            path_params = match.groupdict()
                            break
                    if matched_body:
                        for mw in interpreter_ref.middleware_routes:
                             for stmt in mw: interpreter_ref.visit(stmt)
                        for k, v in path_params.items():
                            interpreter_ref.global_env.set(k, v)
                        for k, v in post_params.items():
                            interpreter_ref.global_env.set(k, v)
                        interpreter_ref.web.stack = []
                        response_body = ""
                        result = None
                        try:
                            for stmt in matched_body:
                                result = interpreter_ref.visit(stmt)
                        except ReturnException as re:
                            result = re.value
                        if interpreter_ref.web.stack:
                             pass
                        if isinstance(result, Tag): response_body = str(result)
                        elif result is not None: response_body = str(result)
                        else: response_body = "OK"
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/html')
                        self.end_headers()
                        if self.command != 'HEAD':
                            try:
                                self.wfile.write(response_body.encode())
                            except (BrokenPipeError, ConnectionResetError): pass
                    else:
                        self.send_response(404)
                        self.end_headers()
                        if self.command != 'HEAD':
                            try:
                                self.wfile.write(b'Not Found')
                            except (BrokenPipeError, ConnectionResetError): pass
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    try:
                        self.send_response(500)
                        self.send_header('Content-Type', 'text/plain')
                        self.end_headers()
                        if self.command != 'HEAD':
                            self.wfile.write(str(e).encode())
                    except: pass
        server = ReusableHTTPServer(('0.0.0.0', port_val), ShellLiteHandler)
        print("\n  ShellLite Server v0.6 is running!")
        print(f"  \u001b[1;36m->\u001b[0m  Local:   \u001b[1;4;36mhttp://localhost:{port_val}/\u001b[0m\n")
        try: server.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")
            pass
    def visit_Download(self, node: Download):
        """
        -----Purpose: Downloads a file from a URL to the local filesystem. 
        -----        Restricted in Safe Mode.
        """
        if self.safe_mode: raise PermissionError("Downloads are disabled in Safe Mode")
        url = self.visit(node.url)
        filename = url.split('/')[-1] or "downloaded_file"
        print(f"Downloading {filename}...")
        try:
             with urllib.request.urlopen(url) as response:
                 with open(filename, 'wb') as f:
                     shutil.copyfileobj(response, f)
             print(f"Download complete: {filename}")
        except Exception as e:
             print(f"Error: Download failed: {e}")

    def visit_ArchiveOp(self, node: ArchiveOp):
        """
        -----Purpose: Compresses or extracts ZIP archives. Restricted in Safe Mode.
        """
        if self.safe_mode: raise PermissionError("Archive operations are disabled in Safe Mode")
        source = str(self.visit(node.source))
        target = str(self.visit(node.target))
        try:
            if node.op == 'compress':
                print(f"Compressing '{source}' to '{target}'...")
                if os.path.isfile(source):
                    with zipfile.ZipFile(target, 'w') as zipf:
                        zipf.write(source, arcname=os.path.basename(source))
                elif os.path.isdir(source):
                    shutil.make_archive(target.replace('.zip', ''), 'zip', source)
                else:
                    print(f"Error: Source '{source}' does not exist.")
                    return
            elif node.op == 'extract':
                print(f"Extracting '{source}' to '{target}'...")
                with zipfile.ZipFile(source, 'r') as zipf:
                    zipf.extractall(target)
                print("Extraction complete.")
        except zipfile.BadZipFile:
            print(f"Error: '{source}' is not a valid zip file.")
        except Exception as e:
            print(f"Error: Archive operation failed: {e}")
    def visit_CsvOp(self, node: CsvOp):
        """
        -----Purpose: Reads or writes CSV files from/to collection nodes.
        """
        path = self.visit(node.path)
        if node.op == 'load':
            with open(path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                return [row for row in reader]
        else:
            data = self.visit(node.data)
            if not isinstance(data, list):
                data = [data]
            if not data:
                return
            rows = []
            for item in data:
                if isinstance(item, Instance):
                    rows.append(item.data)
                elif isinstance(item, dict):
                    rows.append(item)
                else:
                    msg = (
                        "Error: Only lists of objects/dictionaries "
                        "can be saved to CSV."
                    )
                    print(msg)
                    return
            if rows:
                try:
                    keys = rows[0].keys()
                    with open(path, 'w', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=keys)
                        writer.writeheader()
                        writer.writerows(rows)
                    print(f"Saved {len(rows)} rows to '{path}'.")
                except Exception as e:
                    print(f"Error saving CSV: {e}")

    def visit_ClipboardOp(self, node: ClipboardOp):
        """
        -----Purpose: Accesses the system clipboard (copy/paste).
        """
        if 'pyperclip' not in sys.modules:
            msg = "Install 'pyperclip' for clipboard support."
            raise RuntimeError(msg)
        if node.op == 'copy':
             content = str(self.visit(node.content))
             pyperclip.copy(content)
        else:
             return pyperclip.paste()
    def visit_AutomationOp(self, node: AutomationOp):
        """
        -----Purpose: Performs hardware automation tasks (keyboard, mouse).
        -----        Restricted in Safe Mode.
        """
        if self.safe_mode: raise PermissionError("Automation is disabled in Safe Mode")
        args = [self.visit(a) for a in node.args]
        if node.action == 'press':
             if 'keyboard' not in sys.modules:
                 raise RuntimeError("Install 'keyboard'")
             keyboard.press_and_release(args[0])
        elif node.action == 'type':
             if 'keyboard' not in sys.modules:
                 raise RuntimeError("Install 'keyboard'")
             keyboard.write(str(args[0]))
        elif node.action == 'click':
             if 'mouse' not in sys.modules:
                 raise RuntimeError("Install 'mouse'")
             mouse.move(args[0], args[1], absolute=True, duration=0.2)
             mouse.click('left')
        elif node.action == 'notify':
             if 'plyer' not in sys.modules:
                 raise RuntimeError("Install 'plyer'")
             notification.notify(title=str(args[0]), message=str(args[1]))
    def visit_DateOp(self, node: DateOp):
        """
        -----Purpose: Evaluates relative date strings (today, tomorrow, etc.).
        """
        if node.expr == 'today':
            return datetime.now().strftime("%Y-%m-%d")
        today = datetime.now()
        s = node.expr.lower().strip()
        if s == 'tomorrow':
            d = today + timedelta(days=1)
            return d.strftime("%Y-%m-%d")
        elif s == 'yesterday':
            d = today - timedelta(days=1)
            return d.strftime("%Y-%m-%d")
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        if s.startswith('next '):
            day_str = s.replace('next ', '').strip()
            if day_str in days:
                 target_idx = days.index(day_str)
                 current_idx = today.weekday()
                 days_ahead = target_idx - current_idx
                 if days_ahead <= 0: days_ahead += 7
                 d = today + timedelta(days=days_ahead)
                 return d.strftime("%Y-%m-%d")
        return s
    def visit_FileWrite(self, node: FileWrite):
        """
        -----Purpose: Writes or appends content to a file. Restricted in Safe Mode.
        """
        if self.safe_mode: raise PermissionError("File writing is disabled in Safe Mode")
        path = str(self.visit(node.path))
        content = str(self.visit(node.content))
        try:
            with open(path, node.mode, encoding='utf-8') as f:
                f.write(content)
            print(f"{'Appended to' if node.mode == 'a' else 'Written to'} file '{path}'")
        except Exception as e:
            msg = f"File operation failed: {e}"
            raise RuntimeError(msg)
    def visit_FileRead(self, node: FileRead):
        """
        -----Purpose: Reads the entire content of a file. Restricted in Safe Mode.
        """
        if self.safe_mode: raise PermissionError("File reading is disabled in Safe Mode")
        path = str(self.visit(node.path))
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
             raise FileNotFoundError(f"File '{path}' not found.")
    def _builtin_upper(self, s, only=None):
        """
        -----Purpose: Builtin helper to convert string to uppercase.
        """
        if isinstance(s, list):
            return [self._builtin_upper(x, only=only) for x in s]
        
        s_str = str(s)
        if only == 'letters':
            return re.sub(r'[^a-zA-Z\s]', '', s_str).upper()
        return s_str.upper()

    def _builtin_sum_range(self, start, end, condition=None):
        """
        -----Purpose: Builtin helper to sum a range with optional filtering.
        """
        total = 0
        s = int(start)
        e = int(end)
        for i in range(s, e + 1):
             include = True
             if condition == 'even' and i % 2 != 0: include = False
             elif condition == 'odd' and i % 2 == 0: include = False
             elif condition == 'prime':
                 if i < 2: include = False
                 else:
                     for k in range(2, int(i ** 0.5) + 1):
                         if i % k == 0:
                             include = False
                             break
             elif condition == 'digits':
                  pass
             if include:
                 total += i
        return total

    def _builtin_range_list(self, start, end, condition=None):
        res = []
        s = int(start)
        e = int(end)
        for i in range(s, e + 1):
             include = True
             if condition == 'even' and i % 2 != 0: include = False
             elif condition == 'odd' and i % 2 == 0: include = False
             elif condition == 'prime':
                 if i < 2: include = False
                 else:
                     for k in range(2, int(i ** 0.5) + 1):
                         if i % k == 0:
                             include = False
                             break
             if include:
                 res.append(i)
        return res

    def visit_TestBlock(self, node: TestBlock):
        try:
            for stmt in node.body:
                self.visit(stmt)
            print(f"\033[92m[PASS]\033[0m {node.name}")
        except AssertionError as e:
            print(f"\033[91m[FAIL]\033[0m {node.name}: {e}")
        except Exception as e:
            print(f"\033[91m[ERROR]\033[0m {node.name}: {e}")

    def visit_Assertion(self, node: Assertion):
        left_val = self.visit(node.left)
        if node.right is None:
            if not left_val:
                raise AssertionError(f"Expected truthy, got {left_val}")
            return
            
        right_val = self.visit(node.right)
        if node.op == '==':
            if left_val != right_val:
                raise AssertionError(f"Expected {right_val}, got {left_val}")
        elif node.op == '!=':
            if left_val == right_val:
                raise AssertionError(f"Expected not {right_val}, got {left_val}")
        else:
            raise NotImplementedError(f"Assertion op {node.op} not implemented")

    def visit_MaxNode(self, node: MaxNode):
        """
        -----Purpose: Evaluates the maximum of two expressions or a list.
        """
        left_val = self.visit(node.left)
        if node.right:
            right_val = self.visit(node.right)
            return max(left_val, right_val)
        else:
            if isinstance(left_val, (list, tuple)) and left_val:
                return max(left_val)
            return left_val

    def visit_MinNode(self, node: MinNode):
        """
        -----Purpose: Evaluates the minimum of two expressions.
        """
        val1 = self.visit(node.left)
        if node.right:
            return min(val1, self.visit(node.right))
        return min(val1)

    def visit_ClampNode(self, node: ClampNode):
        v = self.visit(node.value)
        lo = self.visit(node.min_val)
        hi = self.visit(node.max_val)
        return max(lo, min(v, hi))

    def visit_LerpNode(self, node: LerpNode):
        a = self.visit(node.start)
        b = self.visit(node.end)
        t = self.visit(node.alpha)
        return a + (b - a) * t
