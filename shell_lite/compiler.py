import random
from typing import List

from .ast_nodes import *


class Compiler:
    """
    -----Purpose: Compiles the custom AST nodes down to executing Python source code.
    """
    def __init__(self):
        self.indentation = 0
    def indent(self):
        """
        -----Purpose: Returns a string of spaces based on current indentation.
        """
        return "    " * self.indentation
    def visit(self, node: Node) -> str:
        method_name = f'visit_{type(node).__name__}'
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)
    def generic_visit(self, node: Node):
        raise Exception(f"Compiler does not support {type(node).__name__}")
    def compile_block(self, statements: List[Node]) -> str:
        """
        -----Purpose: Compiles a list of AST nodes into a single string of 
        -----        indented Python code.
        """
        if not statements:
            return f"{self.indent()}pass"
        code = ""
        for stmt in statements:
            stmt_code = self.visit(stmt)
            is_expr = isinstance(
                stmt, (Number, String, Boolean, Regex, ListVal, 
                       Dictionary, SetVal, VarAccess, BinOp, 
                       UnaryOp, Call, MethodCall, PropertyAccess, 
                       IndexAccess, Await)
            )
            is_block_call = isinstance(stmt, Call) and stmt.body
            if is_expr and not is_block_call:
                stmt_code = (
                    f"_slang_ret = {stmt_code}\n"
                    f"_web_builder.add_text(_slang_ret)"
                )
            indented_stmt = "\n".join(
                [f"{self.indent()}{line}" for line in stmt_code.split('\n')]
            )
            code += indented_stmt + "\n"
        return code.rstrip()
    def compile(self, statements: List[Node]) -> str:
        """
        -----Purpose: Compiles the full script, including imports and the 
        -----        web DSL support runtime.
        """
        code = [
            "import sys",
            "import os",
            "import re",
            "import time",
            "import math",
            "import random",
            "import json",
            "import threading",
            "import concurrent.futures",
            "from http.server import HTTPServer, BaseHTTPRequestHandler",
            "from shell_lite.runtime import *",
            "",
            "# Initialize Runtime Helpers",
            "builtins_map = get_builtins()",
            "globals().update(builtins_map)",
            "",
            "class DotDict(dict):",
            "    def __getattr__(self, key):",
            "        try:",
            "            return self[key]",
            "        except KeyError:",
            "            raise AttributeError(key)",
            "    def __setattr__(self, key, value):",
            "        self[key] = value",
            "",
            "STD_MODULES = get_std_modules()",
            "# Wrap modules",
            "for k, v in STD_MODULES.items():",
            "    if isinstance(v, dict): STD_MODULES[k] = DotDict(v)",
            "",
            "# Async Executor",
            "_executor = concurrent.futures.ThreadPoolExecutor()",
            "",
            "# HTTP Server Support",
            "GLOBAL_ROUTES = {}",
            "GLOBAL_STATIC_ROUTES = {}",
            "",
            "class ShellLiteHTTPHandler(BaseHTTPRequestHandler):",
            "    def do_GET(self):",
            "        self.handle_req()",
            "    def do_POST(self):",
            "        self.handle_req()",
            "    def handle_req(self):",
            "        path = self.path",
            "        # Static Routes",
            "        for prefix, folder in GLOBAL_STATIC_ROUTES.items():",
            "            if path.startswith(prefix):",
            "                clean_path = path[len(prefix):]",
            "                if clean_path.startswith('/'):",
            "                    clean_path = clean_path[1:]",
            "                if clean_path == '': clean_path = 'index.html'",
            "                file_path = os.path.join(folder, clean_path)",
            "                if os.path.exists(file_path) and \\",
            "                   os.path.isfile(file_path):",
            "                     self.send_response(200)",
            "                     # Simple mime type guessing",
            "                     if file_path.endswith('.css'):",
            "                         settings = 'text/css'",
            "                     elif file_path.endswith('.js'):",
            "                         settings = 'application/javascript'",
            "                     elif file_path.endswith('.html'):",
            "                         settings = 'text/html'",
            "                     else:",
            "                         settings = 'application/octet-stream'",
            "                     self.send_header('Content-type', settings)",
            "                     self.end_headers()",
            "                     with open(file_path, 'rb') as f:",
            "                         self.wfile.write(f.read())",
            "                     return",
            "        handler = GLOBAL_ROUTES.get(path)",
            "        if handler:",
            "            try:",
            "                res = handler()",
            "                self.send_response(200)",
            "                self.end_headers()",
            "                if res: self.wfile.write(str(res).encode())",
            "                else: self.wfile.write(b'OK')",
            "            except Exception as e:",
            "                self.send_response(500)",
            "                self.wfile.write(str(e).encode())",
            "        else:",
            "            self.send_response(404)",
            "            self.wfile.write(b'Not Found')",
            "",
            "# --- Web DSL Support ---",
            "class Tag:",
            "    def __init__(self, name, attrs=None):",
            "        self.name = name",
            "        self.attrs = attrs or {}",
            "        self.children = []",
            "    def add(self, child):",
            "        self.children.append(child)",
            "    def __str__(self):",
            "        attr_str = ''.join("
            "[f' {k}=\"{v}\"' for k,v in self.attrs.items()])",
            "        inner = ''.join([str(c) for c in self.children])",
            "        if self.name in ('img', 'br', 'hr', 'input', "
            "'meta', 'link'):",
            "            return f'<{self.name}{attr_str} />'",
            "        return f'<{self.name}{attr_str}>{inner}</{self.name}>'",
            "",
            "class WebBuilder:",
            "    def __init__(self): self.stack = []",
            "    def push(self, tag):",
            "        if self.stack: self.stack[-1].add(tag)",
            "        self.stack.append(tag)",
            "    def pop(self): "
            "return self.stack.pop() if self.stack else None",
            "    def add_text(self, text):",
            "        if self.stack: self.stack[-1].add(text)",
            "        else: pass # Top level text?",
            "",
            "_web_builder = WebBuilder()",
            "",
            "class BuilderContext:",
            "    def __init__(self, tag): self.tag = tag",
            "    def __enter__(self):",
            "        _web_builder.push(self.tag)",
            "        return self.tag",
            "    def __exit__(self, *args): _web_builder.pop()",
            "",
            "def _make_tag_fn(name):",
            "    def fn(*args):",
            "        attrs = {}",
            "        content = []",
            "        for arg in args:",
            "            if isinstance(arg, dict):",
            "                attrs.update(arg)",
            "            elif isinstance(arg, str) and '=' in arg "
            "and ' ' not in arg:",
            "                k, v = arg.split('=', 1)",
            "                attrs[k] = v",
            "            else:",
            "                content.append(arg)",
            "        t = Tag(name, attrs)",
            "        for c in content:",
            "            t.add(c)",
            "        return t",
            "    return fn",
            "",
            "for t in ['div', 'p', 'h1', 'h2', 'h3', 'h4', 'span', 'a',",
            "          'img', 'button', 'input', 'form', 'ul', 'li',",
            "          'html', 'head', 'body', 'title', 'meta', 'link',",
            "          'script', 'style', 'br', 'hr']:",
            "    globals()[t] = _make_tag_fn(t)",
            "",
        ]
        code.append("# --- User Script ---")
        code.append(self.compile_block(statements))
        return "\n".join(code)
    def visit_Number(self, node: Number):
        return str(node.value)
    def visit_String(self, node: String):
        return repr(node.value)
    def visit_Boolean(self, node: Boolean):
        return str(node.value)
    def visit_Regex(self, node: Regex):
        return f"re.compile({repr(node.pattern)})"
    def visit_ListVal(self, node: ListVal):
        elements = []
        for e in node.elements:
            if isinstance(e, Spread):
                elements.append(f"*{self.visit(e.value)}")
            else:
                elements.append(self.visit(e))
        return f"[{', '.join(elements)}]"
    def visit_Dictionary(self, node: Dictionary):
        pairs = [f"{self.visit(k)}: {self.visit(v)}" for k, v in node.pairs]
        return f"{{{', '.join(pairs)}}}"
    def visit_SetVal(self, node: SetVal):
        elements = [self.visit(e) for e in node.elements]
        return f"{{{', '.join(elements)}}}"
    def visit_VarAccess(self, node: VarAccess):
        return node.name
    def visit_Assign(self, node: Assign):
        return f"{node.name} = {self.visit(node.value)}"
    def visit_ConstAssign(self, node: ConstAssign):
        return f"{node.name} = {self.visit(node.value)}"
    def visit_PropertyAssign(self, node: PropertyAssign):
        return f"{node.instance_name}.{node.property_name} = {self.visit(node.value)}"
    def visit_BinOp(self, node: BinOp):
        """
        -----Purpose: Compiles binary operations, including custom 'matches'.
        """
        left = self.visit(node.left)
        right = self.visit(node.right)
        op = node.op
        if op == 'matches':
            return f"bool(re.search(str({right}), str({left})))"
        elif op == 'and' or op == 'or':
             return f"({left} {op} {right})"
        return f"({left} {op} {right})"
    def visit_UnaryOp(self, node: UnaryOp):
        return f"({node.op} {self.visit(node.right)})"
    def visit_Print(self, node: Print):
        if node.color or node.style:
            return f"slang_color_print({self.visit(node.expression)}, {repr(node.color)}, {repr(node.style)})"
        return f"print({self.visit(node.expression)})"
    def visit_Input(self, node: Input):
        if node.prompt:
            return f"input({repr(node.prompt)})"
        return "input()"
    def visit_If(self, node: If):
        code = f"if {self.visit(node.condition)}:\n"
        self.indentation += 1
        code += self.compile_block(node.body)
        self.indentation -= 1
        if node.else_body:
            code += f"\n{self.indent()}else:\n"
            self.indentation += 1
            code += self.compile_block(node.else_body)
            self.indentation -= 1
        return code
    def visit_While(self, node: While):
        code = f"while {self.visit(node.condition)}:\n"
        self.indentation += 1
        code += self.compile_block(node.body)
        self.indentation -= 1
        return code
    def visit_For(self, node: For):
        """
        -----Purpose: Compiles a count-based loop using range().
        """
        code = f"for _ in range({self.visit(node.count)}):\n"
        self.indentation += 1
        code += self.compile_block(node.body)
        self.indentation -= 1
        return code

    def visit_ForIn(self, node: ForIn):
        """
        -----Purpose: Compiles a standard for-in loop over an iterable.
        """
        code = f"for {node.var_name} in {self.visit(node.iterable)}:\n"
        self.indentation += 1
        code += self.compile_block(node.body)
        self.indentation -= 1
        return code
    def visit_Repeat(self, node: Repeat):
        return self.visit_For(For(node.count, node.body))
    def visit_Forever(self, node: Forever):
        code = "while True:\n"
        self.indentation += 1
        code += self.compile_block(node.body)
        self.indentation -= 1
        return code
    def visit_Until(self, node: Until):
         code = f"while not ({self.visit(node.condition)}):\n"
         self.indentation += 1
         code += self.compile_block(node.body)
         self.indentation -= 1
         return code
    def visit_ProgressLoop(self, node: ProgressLoop):
        """
        -----Purpose: Compiles a progress-tracked loop with a console bar.
        """
        loop = node.loop_node
        if isinstance(loop, (For, Repeat)):
             count_expr = self.visit(loop.count)
             code = f"_total = {count_expr}\n"
             code += f"{self.indent()}for _i in range(_total):\n"
             self.indentation += 1
             code += f"{self.indent()}_pct = int((_i/(_total or 1))*100)\n"
             p_bar = (
                 "print(f'Progress: [{{(\"=\"*(_pct//5)):<20}}] "
                 "{_pct}%', end='\\r')"
             )
             code += f"{self.indent()}{p_bar}\n"
             code += self.compile_block(loop.body)
             self.indentation -= 1
             code += f"\n{self.indent()}print(f'Progress: [{{(\"=\"*20)}}] 100%')"
             return code
        elif isinstance(loop, ForIn):
             iter_expr = self.visit(loop.iterable)
             code = f"_iter = list({iter_expr})\n"
             code += f"{self.indent()}_total = len(_iter)\n"
             code += f"{self.indent()}for _i, {loop.var_name} in enumerate(_iter):\n"
             self.indentation += 1
             code += f"{self.indent()}_pct = int((_i/(_total or 1))*100)\n"
             p_bar = (
                 "print(f'Progress: [{{(\"=\"*(_pct//5)):<20}}] "
                 "{_pct}%', end='\\r')"
             )
             code += f"{self.indent()}{p_bar}\n"
             code += self.compile_block(loop.body)
             self.indentation -= 1
             code += f"\n{self.indent()}print(f'Progress: [{{(\"=\"*20)}}] 100%')"
             return code
        return "# Progress only supported for range/in loops"
    def visit_Convert(self, node: Convert):
        if node.target_format.lower() == 'json':
            return f"slang_json_stringify({self.visit(node.expression)})"
        raise ValueError(f"Unknown conversion format: {node.target_format}")
    def visit_Download(self, node: Download):
        return f"slang_download({self.visit(node.url)})"
    def visit_ArchiveOp(self, node: ArchiveOp):
        """
        -----Purpose: Compiles zip/unzip archive operations.
        """
        src = self.visit(node.source)
        trg = self.visit(node.target)
        return f"slang_archive({repr(node.op)}, {src}, {trg})"
    def visit_CsvOp(self, node: CsvOp):
        if node.op == 'load':
            return f"slang_csv_load({self.visit(node.path)})"
        else:
            return f"slang_csv_save({self.visit(node.data)}, {self.visit(node.path)})"
    def visit_ClipboardOp(self, node: ClipboardOp):
        if node.op == 'copy':
             return f"slang_clipboard_copy({self.visit(node.content)})"
        else:
             return "slang_clipboard_paste()"
    def visit_AutomationOp(self, node: AutomationOp):
        args = [self.visit(a) for a in node.args]
        if node.action == 'press': return f"slang_press({args[0]})"
        if node.action == 'type': return f"slang_type({args[0]})"
        if node.action == 'click': return f"slang_click({args[0]}, {args[1]})"
        if node.action == 'notify': return f"slang_notify({args[0]}, {args[1]})"
        return "pass"
    def visit_DateOp(self, node: DateOp):
        return f"slang_date_parse({repr(node.expr)})"
    def visit_FileWrite(self, node: FileWrite):
        """
        -----Purpose: Compiles a file write operation using runtime helpers.
        """
        path = self.visit(node.path)
        cont = self.visit(node.content)
        return f"slang_file_write({path}, {cont}, {repr(node.mode)})"
    def visit_FileRead(self, node: FileRead):
        return f"slang_file_read({self.visit(node.path)})"
    def visit_DatabaseOp(self, node: DatabaseOp):
        if node.op == 'open': return f"slang_db_open({self.visit(node.args[0])})"
        if node.op == 'close': return "slang_db_close()"
        if node.op == 'exec':
             params = self.visit(node.args[1]) if len(node.args) > 1 else "[]"
             return f"slang_db_exec({self.visit(node.args[0])}, {params})"
        if node.op == 'query':
             params = self.visit(node.args[1]) if len(node.args) > 1 else "[]"
             return f"slang_db_query({self.visit(node.args[0])}, {params})"
        return "None"
    def visit_Every(self, node: Every):
        interval = self.visit(node.interval)
        if node.unit == 'minutes': interval = f"({interval} * 60)"
        code = "while True:\n"
        self.indentation += 1
        code += self.compile_block(node.body)
        code += f"\n{self.indent()}time.sleep({interval})"
        self.indentation -= 1
        return code
    def visit_After(self, node: After):
        delay = self.visit(node.delay)
        if node.unit == 'minutes': delay = f"({delay} * 60)"
        code = f"time.sleep({delay})\n"
        code += self.compile_block(node.body)
        return code
    def visit_FunctionDef(self, node: FunctionDef):
        """
        -----Purpose: Compiles a ShellLite function into a Python def.
        """
        args_strs = []
        has_default = False
        for arg_name, default_node, type_hint in node.args:
            if default_node:
                args_strs.append(f"{arg_name}={self.visit(default_node)}")
                has_default = True
            else:
                if has_default:
                    msg = (
                        f"Non-default argument '{arg_name}' follows "
                        f"default argument in function '{node.name}'"
                    )
                    raise SyntaxError(msg)
                args_strs.append(arg_name)
        code = f"def {node.name}({', '.join(args_strs)}):\n"
        old_indent = self.indentation
        self.indentation = 1
        code += f"{self.indent()}_slang_ret = None\n"
        code += self.compile_block(node.body)
        code += f"\n{self.indent()}return _slang_ret"
        self.indentation = old_indent
        return code
    def visit_Return(self, node: Return):
        return f"return {self.visit(node.value)}"
    def visit_Call(self, node: Call):
        args = [self.visit(a) for a in node.args]
        if node.kwargs:
            for k, v in node.kwargs:
                args.append(f"{k}={self.visit(v)}")
        call_expr = f"{node.name}({', '.join(args)})"
        if node.body:
             var_name = f"_tag_{random.randint(0, 1000000)}"
             code = f"{var_name} = {call_expr}\n"
             code += f"with BuilderContext({var_name}):\n"
             old_indent = self.indentation
             self.indentation = 1
             code += self.compile_block(node.body)
             self.indentation = old_indent
             code += f"\n_slang_ret = {var_name}"
             code += f"\n_web_builder.add_text({var_name})"
             return code
        return call_expr
    def visit_ClassDef(self, node: ClassDef):
        """
        -----Purpose: Compiles a ShellLite class into a Python class.
        """
        parent = node.parent if node.parent else "Instance"
        code = f"class {node.name}({parent}):\n"
        self.indentation += 1
        args = ["self"]
        assigns = []
        for prop in node.properties:
            if isinstance(prop, tuple):
                name, default = prop
                if default:
                    args.append(f"{name}={self.visit(default)}")
                else:
                    args.append(name)
                assigns.append(f"self.{name} = {name}")
            else:
                args.append(prop)
                assigns.append(f"self.{prop} = {prop}")
        if not assigns:
            assigns = ["pass"]
        code += f"{self.indent()}def __init__({', '.join(args)}):\n"
        self.indentation += 1
        for assign in assigns:
            code += f"{self.indent()}{assign}\n"
        self.indentation -= 1
        for method in node.methods:
            m_args = ["self"]
            for arg_name, default_node, type_hint in method.args:
                if default_node:
                    m_args.append(f"{arg_name}={self.visit(default_node)}")
                else:
                    m_args.append(arg_name)
            code += (
                f"\n{self.indent()}def {method.name}({', '.join(m_args)}):\n"
            )
            self.indentation += 1
            code += self.compile_block(method.body)
            self.indentation -= 1
        self.indentation -= 1
        return code
    def visit_Instantiation(self, node: Instantiation):
        args = [self.visit(a) for a in node.args]
        return f"{node.var_name} = {node.class_name}({', '.join(args)})"
    def visit_Make(self, node: Make):
         args = [self.visit(a) for a in node.args]
         return f"{node.class_name}({', '.join(args)})"
    def visit_MethodCall(self, node: MethodCall):
        args = [self.visit(a) for a in node.args]
        return f"{node.instance_name}.{node.method_name}({', '.join(args)})"
    def visit_PropertyAccess(self, node: PropertyAccess):
        return f"{node.instance_name}.{node.property_name}"
    def visit_Import(self, node: Import):
        if node.path in ('math', 'time', 'http', 'env', 'args', 'path', 're'):
             return f"{node.path} = STD_MODULES['{node.path}']"
        else:
             base = os.path.basename(node.path).replace('.shl', '').replace('.py', '')
             return f"import {base}"
    def visit_ImportAs(self, node: ImportAs):
        """
        -----Purpose: Compiles prioritized imports with aliases.
        """
        if node.path in ('math', 'time', 'http', 'env', 'args', 'path', 're'):
             return f"{node.alias} = STD_MODULES['{node.path}']"
        base = os.path.basename(node.path).replace('.shl', '')
        base = base.replace('.py', '')
        return f"import {base} as {node.alias}"
    def visit_Try(self, node: Try):
        code = "try:\n"
        self.indentation += 1
        code += self.compile_block(node.try_body)
        self.indentation -= 1
        code += f"\n{self.indent()}except Exception as {node.catch_var}:\n"
        self.indentation += 1
        code += self.compile_block(node.catch_body)
        self.indentation -= 1
        return code
    def visit_TryAlways(self, node: TryAlways):
        code = "try:\n"
        self.indentation += 1
        code += self.compile_block(node.try_body)
        self.indentation -= 1
        if node.catch_body:
            code += f"\n{self.indent()}except Exception as {node.catch_var}:\n"
            self.indentation += 1
            code += self.compile_block(node.catch_body)
            self.indentation -= 1
        code += f"\n{self.indent()}finally:\n"
        self.indentation += 1
        code += self.compile_block(node.always_body)
        self.indentation -= 1
        return code
    def visit_Throw(self, node: Throw):
        return f"raise Exception({self.visit(node.message)})"
    def visit_Stop(self, node: Stop): return "break"
    def visit_Skip(self, node: Skip): return "continue"
    def visit_Exit(self, node: Exit):
        code = self.visit(node.code) if node.code else "0"
        return f"sys.exit({code})"
    def visit_ListComprehension(self, node: ListComprehension):
        """
        -----Purpose: Compiles a list comprehension.
        """
        iter_str = self.visit(node.iterable)
        expr_str = self.visit(node.expr)
        c_str = ""
        if node.condition:
            c_str = f" if {self.visit(node.condition)}"
        return f"[{expr_str} for {node.var_name} in {iter_str}{c_str}]"
    def visit_Lambda(self, node: Lambda):
        return f"lambda {', '.join(node.params)}: {self.visit(node.body)}"
    def visit_Ternary(self, node: Ternary):
        return f"({self.visit(node.true_expr)} if {self.visit(node.condition)} else {self.visit(node.false_expr)})"
    def visit_Spawn(self, node: Spawn):
        if isinstance(node.call, Call):
            args = [self.visit(a) for a in node.call.args]
            return f"_executor.submit({node.call.name}, {', '.join(args)})"
        return f"_executor.submit({self.visit(node.call)})"
    def visit_Await(self, node: Await):
        task = self.visit(node.task)
        return f"( {task}.result() if hasattr({task}, 'result') else {task} )"
    
    # --- Epic 3: Concurrency ---
    def visit_Parallel(self, node: Parallel):
        code = "[\n"
        self.indentation += 1
        for stmt in node.body:
            code += f"{self.indent()}_executor.submit(lambda: {self.visit(stmt)}),\n"
        self.indentation -= 1
        code += f"{self.indent()}]"
        return code

    def visit_Gather(self, node: Gather):
        return f"[f.result() if hasattr(f, 'result') else f for f in {self.visit(node.tasks)}]"

    def visit_Lock(self, node: Lock):
        lock_name = f"_lock_{node.name}"
        code = f"if '{lock_name}' not in globals(): globals()['{lock_name}'] = threading.Lock()\n"
        code += f"{self.indent()}with globals()['{lock_name}']:\n"
        self.indentation += 1
        code += self.compile_block(node.body)
        self.indentation -= 1
        return code

    def visit_Channel(self, node: Channel):
        return "queue.Queue()"

    def visit_Send(self, node: Send):
        return f"{self.visit(node.channel)}.put({self.visit(node.value)})"

    def visit_Receive(self, node: Receive):
        return f"{self.visit(node.channel)}.get()"

    # --- Epic 5: ORM (Oracle) ---
    def visit_ModelDef(self, node: ModelDef):
        # Transpiled to a simple dict representation for the runtime to use
        fields = {name: ftype for name, ftype in node.fields}
        return f"builtins_map['models']['{node.name}'] = {repr(fields)}"

    def visit_CreateTable(self, node: CreateTable):
        return f"slang_db_create_table('{node.model_name}')"

    def visit_InsertRecord(self, node: InsertRecord):
        values = {k: self.visit(v) for k, v in node.values}
        val_str = "{" + ", ".join([f"'{k}': {v}" for k, v in values.items()]) + "}"
        return f"slang_db_insert('{node.model_name}', {val_str})"

    def visit_FindRecords(self, node: FindRecords):
        conds = []
        for f, op, v in node.conditions:
            conds.append(f"('{f}', '{op}', {self.visit(v)})")
        conds_str = "[" + ", ".join(conds) + "]"
        return f"slang_db_find('{node.model_name}', {conds_str}, {node.find_all})"

    def visit_UpdateRecords(self, node: UpdateRecords):
        conds = []
        for f, op, v in node.conditions:
            conds.append(f"('{f}', '{op}', {self.visit(v)})")
        upds = []
        for f, v in node.updates:
            upds.append(f"('{f}', {self.visit(v)})")
        
        conds_str = "[" + ", ".join(conds) + "]"
        upds_str = "[" + ", ".join(upds) + "]"
        return f"slang_db_update('{node.model_name}', {conds_str}, {upds_str})"

    def visit_DeleteRecords(self, node: DeleteRecords):
        conds = []
        for f, op, v in node.conditions:
            conds.append(f"('{f}', '{op}', {self.visit(v)})")
        conds_str = "[" + ", ".join(conds) + "]"
        return f"slang_db_delete('{node.model_name}', {conds_str})"

    def visit_Listen(self, node: Listen):
        """
        -----Purpose: Compiles the HTTP server start command.
        """
        port = self.visit(node.port)
        code = f"server_address = ('', {port})\n"
        h_setup = (
            "httpd = HTTPServer(server_address, ShellLiteHTTPHandler)"
        )
        code += f"{self.indent()}{h_setup}\n"
        prnt = "print(f'Serving on port {server_address[1]}...')"
        code += f"{self.indent()}{prnt}\n"
        code += f"{self.indent()}httpd.serve_forever()"
        return code
    def visit_ServeStatic(self, node: ServeStatic):
         return f"GLOBAL_STATIC_ROUTES[{self.visit(node.url)}] = {self.visit(node.folder)}"
    def visit_OnRequest(self, node: OnRequest):
        """
        -----Purpose: Registers a route handler for the HTTP server.
        """
        path = self.visit(node.path)
        u_id = random.randint(0, 1000)
        func_name = f"route_handler_{abs(hash(str(node.path)))}_{u_id}"
        code = f"def {func_name}():\n"
        old_indent = self.indentation
        self.indentation = 1
        code += f"{self.indent()}_slang_ret = None\n"
        code += self.compile_block(node.body)
        code += f"\n{self.indent()}return _slang_ret"
        self.indentation = old_indent
        code += f"\nGLOBAL_ROUTES[{path}] = {func_name}"
        return code
    def visit_Alert(self, node: Alert):
        return f"slang_alert({self.visit(node.message)})"
    def visit_Prompt(self, node: Prompt):
        return f"slang_prompt({self.visit(node.prompt)})"
    def visit_Confirm(self, node: Confirm):
        return f"slang_confirm({self.visit(node.prompt)})"
    def visit_FileWatcher(self, node: FileWatcher):
        """
        -----Purpose: Compiles a polling file watcher using os.path.getmtime.
        """
        u_id = random.randint(0, 1000)
        path_var = f"fw_path_{u_id}"
        mtime_var = f"fw_mtime_{u_id}"
        code = f"{path_var} = {self.visit(node.path)}\n"
        mt_init = (
            f"os.path.getmtime({path_var}) if "
            f"os.path.exists({path_var}) else 0"
        )
        code += f"{self.indent()}{mtime_var} = {mt_init}\n"
        code += f"{self.indent()}while True:\n"
        self.indentation += 1
        code += f"{self.indent()}time.sleep(1)\n"
        code += f"{self.indent()}if os.path.exists({path_var}):\n"
        self.indentation += 1
        code += f"{self.indent()}curr_mtime = os.path.getmtime({path_var})\n"
        code += f"{self.indent()}if curr_mtime != {mtime_var}:\n"
        self.indentation += 1
        code += f"{self.indent()}{mtime_var} = curr_mtime\n"
        code += self.compile_block(node.body)
        self.indentation -= 1
        self.indentation -= 1
        self.indentation -= 1
        return code