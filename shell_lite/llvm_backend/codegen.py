import os
import sys as _sys
from llvmlite import ir
from ..ast_nodes import *

class LLVMCompiler:
    def __init__(self):
        """
        -----Purpose: Initializes the LLVM module and declares external C 
        -----        runtime functions (printf, malloc, free, etc.).
        """
        self.module = ir.Module(name="shell_lite_module")
        try:
            import llvmlite.binding as llvm
            llvm.initialize()
            llvm.initialize_native_target()
            llvm.initialize_native_asmprinter()
            self.module.triple = llvm.get_default_triple()
        except Exception:
            if _sys.platform == 'win32':
                self.module.triple = 'x86_64-pc-windows-msvc'
            elif _sys.platform == 'darwin':
                self.module.triple = 'x86_64-apple-macosx10.15.0'
            else:
                self.module.triple = 'x86_64-pc-linux-gnu'
        self.int32 = ir.IntType(64)
        self.char_ptr = ir.IntType(8).as_pointer()
        vptr = ir.IntType(8).as_pointer()
        
        prnt_ty = ir.FunctionType(self.int32, [vptr], var_arg=True)
        self.printf = ir.Function(self.module, prnt_ty, name="printf")
        
        m_ty = ir.FunctionType(vptr, [self.int32])
        self.malloc = ir.Function(self.module, m_ty, name="malloc")
        
        f_ty = ir.FunctionType(ir.VoidType(), [vptr])
        self.free = ir.Function(self.module, f_ty, name="free")
        
        slen_ty = ir.FunctionType(self.int32, [vptr])
        self.strlen = ir.Function(self.module, slen_ty, name="strlen")
        
        scpy_ty = ir.FunctionType(vptr, [vptr, vptr])
        self.strcpy = ir.Function(self.module, scpy_ty, name="strcpy")
        
        scat_ty = ir.FunctionType(vptr, [vptr, vptr])
        self.strcat = ir.Function(self.module, scat_ty, name="strcat")
        
        fop_ty = ir.FunctionType(vptr, [vptr, vptr])
        self.fopen = ir.Function(self.module, fop_ty, name="fopen")
        
        fcl_ty = ir.FunctionType(self.int32, [vptr])
        self.fclose = ir.Function(self.module, fcl_ty, name="fclose")
        
        fwr_ty = ir.FunctionType(
            self.int32, [vptr, self.int32, self.int32, vptr]
        )
        self.fwrite = ir.Function(self.module, fwr_ty, name="fwrite")
        
        frd_ty = ir.FunctionType(
            self.int32, [vptr, self.int32, self.int32, vptr]
        )
        self.fread = ir.Function(self.module, frd_ty, name="fread")
        
        fgt_ty = ir.FunctionType(vptr, [vptr, self.int32, vptr])
        self.fgets = ir.Function(self.module, fgt_ty, name="fgets")
        
        fsk_ty = ir.FunctionType(self.int32, [vptr, self.int32, self.int32])
        self.fseek = ir.Function(self.module, fsk_ty, name="fseek")
        
        ftl_ty = ir.FunctionType(self.int32, [vptr])
        self.ftell = ir.Function(self.module, ftl_ty, name="ftell")
        
        rwd_ty = ir.FunctionType(ir.VoidType(), [vptr])
        self.rewind = ir.Function(self.module, rwd_ty, name="rewind")
        
        gst_ty = ir.FunctionType(vptr, [])
        self.get_stdin = ir.Function(
            self.module, gst_ty, name="getchar"
        )
        
        sys_ty = ir.FunctionType(self.int32, [vptr])
        self.system = ir.Function(self.module, sys_ty, name="system")
        
        strcmp_ty = ir.FunctionType(self.int32, [vptr, vptr])
        self.strcmp = ir.Function(self.module, strcmp_ty, name="strcmp")
        
        func_type = ir.FunctionType(self.int32, [], var_arg=False)
        self.main_func = ir.Function(self.module, func_type, name="main")
        block = self.main_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)
        self.scopes = [{}]
        self.loop_stack = []
        self.str_constants = {}
        self.imported_files = set()
    def _get_scope(self):
        return self.scopes[-1]
    def _alloca(self, name, typ=None):
        if typ is None: typ = self.int32
        with self.builder.goto_entry_block():
             ptr = self.builder.alloca(typ, size=None, name=name)
        return ptr
    def _coerce_to_int(self, val):
        if val is None: return ir.Constant(self.int32, 0)
        if val.type == self.char_ptr:
            return self.builder.ptrtoint(val, self.int32)
        if val.type == ir.IntType(1):
            return self.builder.zext(val, self.int32)
        return val
    def compile(self, statements):
        """
        -----Purpose: Iteratively visits statements to generate the final LLVM 
        -----        IR module. Uses a two-pass approach to support forward declarations.
        """
        self._declare_functions_recursive(statements)
        
        for stmt in statements:
            self.visit(stmt)
        self.builder.ret(ir.Constant(self.int32, 0))
        return self.module

    def _declare_functions_recursive(self, statements, visited=None):
        if visited is None: visited = set()
        import os
        from ..lexer import Lexer
        from ..parser_gbp import GeometricBindingParser as Parser
        for stmt in statements:
            if isinstance(stmt, FunctionDef):
                if stmt.name not in self.module.globals:
                    arg_types = [self.char_ptr] * len(stmt.args)
                    func_ty = ir.FunctionType(self.int32, arg_types)
                    ir.Function(self.module, func_ty, name=stmt.name)
            elif isinstance(stmt, Import):
                target_path = stmt.path
                if target_path in ('math', 'time', 'http', 'env', 'args', 'path', 're'):
                    continue
                abs_path = os.path.abspath(target_path)
                if abs_path in visited:
                    continue
                visited.add(abs_path)
                
                if os.path.exists(target_path):
                    with open(target_path, 'r', encoding='utf-8') as f:
                        source = f.read()
                    l = Lexer(source)
                    p = Parser(l.tokenize())
                    imported_stmts = p.parse()
                    self._declare_functions_recursive(imported_stmts, visited)
    def visit(self, node):
        """
        -----Purpose: Dispatcher for the visitor pattern.
        """
        method_name = f"visit_{type(node).__name__}"
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)
    def generic_visit(self, node):
        print(f"Warning: LLVM Backend does not support {type(node).__name__} yet.")
        return None
    def visit_Number(self, node: Number):
        """
        -----Purpose: Generates a 32-bit integer constant.
        """
        return ir.Constant(self.int32, int(node.value))

    def visit_String(self, node: String):
        """
        -----Purpose: Generates a global string constant (char*).
        """
        return self._get_string_constant(node.value)
    def visit_BinOp(self, node: BinOp):
        op = node.op
        if op == '.':
            return ir.Constant(self.int32, 0)
        left = self.visit(node.left)
        right = self.visit(node.right)
        if op == '+':
            is_str_op = False
            if left.type == self.char_ptr or right.type == self.char_ptr:
                is_str_op = True
            if is_str_op:
                if left.type == self.int32:
                    left = self.builder.inttoptr(left, self.char_ptr, name="cast_l")
                if right.type == self.int32:
                    right = self.builder.inttoptr(right, self.char_ptr, name="cast_r")
            if is_str_op:
                 len1 = self.builder.call(self.strlen, [left], name="len1")
                 len2 = self.builder.call(self.strlen, [right], name="len2")
                 t_len = self.builder.add(len1, len2, name="total_len")
                 a_len = self.builder.add(
                     t_len, ir.Constant(self.int32, 1), name="alloc_len"
                 )
                 n_str = self.builder.call(self.malloc, [a_len], name="new_str")
                 self.builder.call(self.strcpy, [n_str, left])
                 self.builder.call(self.strcat, [n_str, right])
                 return n_str
            return self.builder.add(left, right, name="addtmp")
        elif op == '-':
            left = self._coerce_to_int(left)
            right = self._coerce_to_int(right)
            return self.builder.sub(left, right, name="subtmp")
        elif op == '*':
            left = self._coerce_to_int(left)
            right = self._coerce_to_int(right)
            return self.builder.mul(left, right, name="multmp")
        elif op == '/':
            left = self._coerce_to_int(left)
            right = self._coerce_to_int(right)
            return self.builder.sdiv(left, right, name="divtmp")
        elif op == '%':
            left = self._coerce_to_int(left)
            right = self._coerce_to_int(right)
            return self.builder.srem(left, right, name="modtmp")
        elif op in ('==', 'is', '!=', 'is not', '<', '<=', '>', '>='):
            if left.type == self.char_ptr and right.type == self.char_ptr:
                res = self.builder.call(self.strcmp, [left, right])
                if op in ('==', 'is'):
                    return self.builder.icmp_signed('==', res, ir.Constant(self.int32, 0))
                elif op in ('!=', 'is not'):
                    return self.builder.icmp_signed('!=', res, ir.Constant(self.int32, 0))
                elif op == '<':
                    return self.builder.icmp_signed('<', res, ir.Constant(self.int32, 0))
                elif op == '<=':
                    return self.builder.icmp_signed('<=', res, ir.Constant(self.int32, 0))
                elif op == '>':
                    return self.builder.icmp_signed('>', res, ir.Constant(self.int32, 0))
                elif op == '>=':
                    return self.builder.icmp_signed('>=', res, ir.Constant(self.int32, 0))
            
            if left.type != right.type:
                if left.type == self.char_ptr:
                    left = self.builder.ptrtoint(left, self.int32)
                if right.type == self.char_ptr:
                    right = self.builder.ptrtoint(right, self.int32)
            
            if op in ('==', 'is'): return self.builder.icmp_signed('==', left, right)
            if op in ('!=', 'is not'): return self.builder.icmp_signed('!=', left, right)
            if op == '<': return self.builder.icmp_signed('<', left, right)
            if op == '<=': return self.builder.icmp_signed('<=', left, right)
            if op == '>': return self.builder.icmp_signed('>', left, right)
            if op == '>=': return self.builder.icmp_signed('>=', left, right)
        elif op == 'and':
            return self.builder.and_(left, right, name="andtmp")
        elif op == 'or':
            return self.builder.or_(left, right, name="ortmp")
        else:
            msg = f"Unknown operator: {op}"
            raise Exception(msg)
    def visit_If(self, node: If):
        """
        -----Purpose: Generates LLVM branch and basic blocks for an if/else.
        """
        cond_val = self.visit(node.condition)
        cond_val = self._coerce_to_int(cond_val)
        if cond_val.type != ir.IntType(1):
             cond_val = self.builder.icmp_signed(
                 '!=', cond_val, ir.Constant(self.int32, 0), name="ifcond"
             )
        then_bb = self.builder.append_basic_block(name="then")
        else_bb = self.builder.append_basic_block(name="else")
        merge_bb = self.builder.append_basic_block(name="ifcont")
        self.builder.cbranch(cond_val, then_bb, else_bb)
        self.builder.position_at_end(then_bb)
        for stmt in node.body:
            self.visit(stmt)
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_bb)
        self.builder.position_at_end(else_bb)
        if node.else_body:
            for stmt in node.else_body:
                self.visit(stmt)
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_bb)
        self.builder.position_at_end(merge_bb)
    def visit_While(self, node: While):
        """
        -----Purpose: Generates LLVM loop structure (condition, body, after).
        """
        cond_bb = self.builder.append_basic_block(name="loop.cond")
        body_bb = self.builder.append_basic_block(name="loop.body")
        after_bb = self.builder.append_basic_block(name="loop.after")
        self.loop_stack.append((cond_bb, after_bb))
        self.builder.branch(cond_bb)
        self.builder.position_at_end(cond_bb)
        cond_val = self.visit(node.condition)
        cond_val = self._coerce_to_int(cond_val)
        if cond_val.type != ir.IntType(1):
             cond_val = self.builder.icmp_signed(
                 '!=', cond_val, ir.Constant(self.int32, 0), name="loopcond"
             )
        self.builder.cbranch(cond_val, body_bb, after_bb)
        self.builder.position_at_end(body_bb)
        for stmt in node.body:
            self.visit(stmt)
        self.builder.branch(cond_bb)
        self.builder.position_at_end(after_bb)
        self.loop_stack.pop()
    def visit_Repeat(self, node: Repeat):
        """
        -----Purpose: Generates a counter-based repeat loop in LLVM IR.
        """
        count_val = self.visit(node.count)
        import random
        uid = random.randint(0, 10000)
        i_ptr = self._alloca(f"_loop_i_{uid}")
        self.builder.store(ir.Constant(self.int32, 0), i_ptr)
        cond_bb = self.builder.append_basic_block(name="repeat.cond")
        body_bb = self.builder.append_basic_block(name="repeat.body")
        after_bb = self.builder.append_basic_block(name="repeat.after")
        self.loop_stack.append((cond_bb, after_bb))
        self.builder.branch(cond_bb)
        self.builder.position_at_end(cond_bb)
        curr_i = self.builder.load(i_ptr, name="i_load")
        cmp = self.builder.icmp_signed('<', curr_i, count_val, name="loopcheck")
        self.builder.cbranch(cmp, body_bb, after_bb)
        self.builder.position_at_end(body_bb)
        for stmt in node.body:
            self.visit(stmt)
        curr_i_Body = self.builder.load(i_ptr)
        next_i = self.builder.add(curr_i_Body, ir.Constant(self.int32, 1), name="inc_i")
        self.builder.store(next_i, i_ptr)
        self.builder.branch(cond_bb)
        self.builder.position_at_end(after_bb)
        self.loop_stack.pop()
    def visit_FunctionDef(self, node: FunctionDef):
        """
        -----Purpose: Defines a new LLVM function with an isolated scope.
        """
        arg_types = []
        for arg in node.args:
            arg_types.append(self.char_ptr)
        func_ty = ir.FunctionType(self.int32, arg_types)
        if node.name in self.module.globals:
            func = self.module.globals[node.name]
        else:
            func = ir.Function(self.module, func_ty, name=node.name)
        old_builder = self.builder
        block = func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(block)
        self.scopes.append({})
        for i, arg in enumerate(func.args):
            arg_name = node.args[i][0]
            arg.name = arg_name
            ptr = self.builder.alloca(arg.type, name=arg_name)
            self.builder.store(arg, ptr)
            self.scopes[-1][arg_name] = ptr
        for stmt in node.body:
            self.visit(stmt)
        if not self.builder.block.is_terminated:
             self.builder.ret(ir.Constant(self.int32, 0))
        self.scopes.pop()
        self.builder = old_builder
    def visit_Return(self, node: Return):
        """
        -----Purpose: Generates an LLVM return instruction, casting if needed.
        """
        val = self.visit(node.value)
        if val.type == self.char_ptr:
             val = self.builder.ptrtoint(val, self.int32)
        self.builder.ret(val)
    def visit_Call(self, node: Call):
        """
        -----Purpose: Emits an LLVM call instruction for a function.
        """
        if node.name == 'int':
            if len(node.args) > 0:
                return self.visit(node.args[0])
            return ir.Constant(self.int32, 0)
        elif node.name == 'str':
            if len(node.args) > 0:
                val = self.visit(node.args[0])
                if val.type == self.char_ptr:
                    return val
                buf = self.builder.call(self.malloc, [ir.Constant(self.int32, 20)], name="strbuf")
                fmt = self._get_string_constant("%lld")
                self.builder.call(self.printf, [fmt, val])  # placeholder
                return buf
            return self._get_string_constant("")
        elif node.name == 'float':
            if len(node.args) > 0:
                return self.visit(node.args[0])
            return ir.Constant(self.int32, 0)
        elif node.name == 'len':
            if len(node.args) > 0:
                val = self.visit(node.args[0])
                if val.type == self.char_ptr:
                    return self.builder.call(self.strlen, [val], name="lentmp")
            return ir.Constant(self.int32, 0)
        elif node.name == 'ord':
            if len(node.args) > 0:
                val = self.visit(node.args[0])
                if val.type == self.char_ptr:
                    first_char = self.builder.load(val, name="ordtmp")
                    return self.builder.zext(first_char, self.int32, name="ordext")
            return ir.Constant(self.int32, 0)
        elif node.name == 'char':
            if len(node.args) > 0:
                val = self.visit(node.args[0])
                buf = self.builder.call(self.malloc, [ir.Constant(self.int32, 2)], name="charbuf")
                trunc = self.builder.trunc(val, ir.IntType(8), name="chartrunc")
                self.builder.store(trunc, buf)
                null_ptr = self.builder.gep(buf, [ir.Constant(self.int32, 1)])
                self.builder.store(ir.Constant(ir.IntType(8), 0), null_ptr)
                return buf
            return self._get_string_constant("")
        elif node.name == 'contains':
            return ir.Constant(ir.IntType(1), 0)
        elif node.name == 'randint':
            return ir.Constant(self.int32, 0)
        elif node.name == 'abs':
            return ir.Constant(self.int32, 0)
        elif node.name == 'str':
            return self.builder.inttoptr(ir.Constant(self.int32, 0), self.char_ptr)
        elif node.name == 'range':
            return ir.Constant(self.int32, 0)

        if node.name in self.module.globals:
            func = self.module.globals[node.name]
        elif node.name == 'add':
            return ir.Constant(self.int32, 0)
        elif node.name == 'read':
             if len(node.args) > 0:
                 return self.visit_FileRead(FileRead(node.args[0]))
             else:
                 return ir.Constant(self.int32, 0)
        else:
             print(f"Warning: Function {node.name} not found")
             return ir.Constant(self.int32, 0)
        args = [self.visit(a) for a in node.args]
        if func and isinstance(func, ir.Function):
            # Prepare arguments: ensure they match the function signature
            call_args = []
            for i, arg in enumerate(args):
                if i < len(func.function_type.args):
                    expected_ty = func.function_type.args[i]
                    if arg.type != expected_ty:
                        if isinstance(expected_ty, ir.PointerType):
                            arg = self.builder.inttoptr(arg, expected_ty)
                        else:
                            arg = self.builder.ptrtoint(arg, expected_ty)
                call_args.append(arg)
            return self.builder.call(func, call_args, name="calltmp")
        return self.builder.call(func, args, name="calltmp")
    def visit_Assign(self, node: Assign):
        """
        -----Purpose: Generates LLVM alloca (on first use) and store for a var.
        """
        value = self.visit(node.value)
        scope = self._get_scope()
        if node.name not in scope:
            ptr = self._alloca(node.name, typ=value.type)
            scope[node.name] = ptr
        else:
            ptr = scope[node.name]
        self.builder.store(value, ptr)
        return value
    def visit_Execute(self, node: Execute):
        """
        -----Purpose: Emits an LLVM call to the C 'system' function.
        """
        cmd = self.visit(node.code)
        self.builder.call(self.system, [cmd])
        return ir.Constant(self.int32, 0)
    def visit_Stop(self, node: Stop):
        """
        -----Purpose: Generates a branch to the loop's after block.
        """
        if not self.loop_stack:
            print("Error: stop used outside of loop")
            return
        after_bb = self.loop_stack[-1][1]
        self.builder.branch(after_bb)
        dead_bb = self.builder.append_basic_block(name="dead")
        self.builder.position_at_end(dead_bb)
    def visit_Skip(self, node: Skip):
        """
        -----Purpose: Generates a branch to the loop's condition block.
        """
        if not self.loop_stack:
            print("Error: skip used outside of loop")
            return
        cond_bb = self.loop_stack[-1][0]
        self.builder.branch(cond_bb)
        dead_bb = self.builder.append_basic_block(name="dead")
        self.builder.position_at_end(dead_bb)
    def _get_stdin_handle(self):
        return self.builder.call(self.get_stdin, [ir.Constant(self.int32, 0)])
    def visit_Input(self, node: Input):
        """
        -----Purpose: Generates LLVM calls to malloc and fgets for user input.
        """
        buffer_len = ir.Constant(self.int32, 256)
        buffer = self.builder.call(self.malloc, [buffer_len], name="input_buf")
        stdin = self._get_stdin_handle()
        self.builder.call(self.fgets, [buffer, buffer_len, stdin])
        return buffer
    def visit_FileWrite(self, node: FileWrite):
        """
        -----Purpose: Emits LLVM calls to fopen/fwrite/fclose for file output.
        """
        path = self.visit(node.path)
        content = self.visit(node.content)
        mode = self._get_string_constant("w")
        fp = self.builder.call(self.fopen, [path, mode], name="fp")
        length = self.builder.call(self.strlen, [content])
        self.builder.call(
            self.fwrite, [content, ir.Constant(self.int32, 1), length, fp]
        )
        self.builder.call(self.fclose, [fp])
        return ir.Constant(self.int32, 0)
    def visit_FileRead(self, node: FileRead):
        """
        -----Purpose: Emits LLVM calls to read an entire file into a buffer.
        """
        path = self.visit(node.path)
        mode = self._get_string_constant("rb")
        fp = self.builder.call(self.fopen, [path, mode], name="fp")
        self.builder.call(
            self.fseek,
            [fp, ir.Constant(self.int32, 0), ir.Constant(self.int32, 2)]
        )
        size = self.builder.call(self.ftell, [fp], name="fsize")
        self.builder.call(self.rewind, [fp])
        a_size = self.builder.add(size, ir.Constant(self.int32, 1))
        buffer = self.builder.call(self.malloc, [a_size], name="fbuf")
        self.builder.call(
            self.fread, [buffer, ir.Constant(self.int32, 1), size, fp]
        )
        null_term_ptr = self.builder.gep(buffer, [size])
        self.builder.store(ir.Constant(ir.IntType(8), 0), null_term_ptr)
        self.builder.call(self.fclose, [fp])
        return buffer
    def visit_VarAccess(self, node: VarAccess):
        """
        -----Purpose: Emits an LLVM load instruction for a variable.
        """
        if node.name == 'null' or node.name == 'None':
             return ir.Constant(self.char_ptr, None)
        if node.name in ('true', 'yes'):
             return ir.Constant(ir.IntType(1), 1)
        if node.name in ('false', 'no'):
             return ir.Constant(ir.IntType(1), 0)
             
        scope = self._get_scope()
        for s in reversed(self.scopes):
            if node.name in s:
                ptr = s[node.name]
                return self.builder.load(ptr, name=node.name)
        
        msg = f"Variable '{node.name}' not defined"
        raise Exception(msg)
    def _get_string_constant(self, text):
        """
        -----Purpose: Manages a pool of global string constants to avoid 
        -----        redundancy in the LLVM module.
        """
        text += '\0'
        if text in self.str_constants:
            return self.str_constants[text]
        byte_arr = bytearray(text.encode("utf8"))
        c_str_ty = ir.ArrayType(ir.IntType(8), len(byte_arr))
        name = f".str_{len(self.str_constants)}"
        global_var = ir.GlobalVariable(self.module, c_str_ty, name=name)
        global_var.linkage = 'internal'
        global_var.global_constant = True
        global_var.initializer = ir.Constant(c_str_ty, byte_arr)
        ptr = self.builder.bitcast(global_var, self.char_ptr)
        self.str_constants[text] = ptr
        return ptr
    def visit_Print(self, node: Print):
        """
        -----Purpose: Generates an LLVM call to printf for a given expression.
        """
        value = self.visit(node.expression)
        if value.type == self.char_ptr:
            fmt_str = self._get_string_constant("%s\n")
            self.builder.call(self.printf, [fmt_str, value])
        else:
            fmt_str = self._get_string_constant("%lld\n")
            self.builder.call(self.printf, [fmt_str, value])
    def visit_Import(self, node):
        """
        -----Purpose: Parses and visits statements from an imported file.
        """
        import os
        from ..lexer import Lexer
        from ..parser_gbp import GeometricBindingParser as Parser
        
        target_path = node.path
        abs_path = os.path.abspath(target_path)
        if abs_path in self.imported_files:
            return None
        self.imported_files.add(abs_path)
        
        if not os.path.exists(target_path):
            std_modules = ('math', 'time', 'http', 'env', 'args', 'path', 're')
            if node.path in std_modules:
                return None
            print(f"Warning: LLVM import could not find '{node.path}', skipping.")
            return None
        with open(target_path, 'r', encoding='utf-8') as f:
            source = f.read()
        from ..lexer import Lexer
        from ..parser_gbp import GeometricBindingParser as Parser
        lexer = Lexer(source)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        statements = parser.parse()
        for stmt in statements:
            self.visit(stmt)
    def visit_ConstAssign(self, node):
        """
        -----Purpose: Handles constant assignments (same as regular assigns in LLVM).
        """
        return self.visit_Assign(Assign(name=node.name, value=node.value))
    def visit_Boolean(self, node):
        """
        -----Purpose: Generates a 32-bit integer constant for a boolean (1 or 0).
        """
        return ir.Constant(self.int32, 1 if node.value else 0)

    def visit_UnaryOp(self, node):
        """
        -----Purpose: Generates LLVM IR for unary operations (not, negation).
        """
        val = self.visit(node.right)
        if node.op == 'not':
            if val.type == self.char_ptr:
                val = self.builder.ptrtoint(val, self.int32)
            if val.type == ir.IntType(1):
                return self.builder.not_(val, name="nottmp")
            zero = ir.Constant(val.type, 0)
            cmp = self.builder.icmp_signed('==', val, zero, name="notcmp")
            return cmp
        elif node.op == '-':
            zero = ir.Constant(val.type, 0)
            return self.builder.sub(zero, val, name="negtmp")
        raise Exception(f"Unknown unary operator: {node.op}")
    def visit_ForIn(self, node):
        """
        -----Purpose: Generates a for-in loop over a range (limited LLVM support).
        -----        Supports 'range(start, end)' style iteration.
        """
        import random
        if isinstance(node.iterable, Call) and node.iterable.name == 'range':
            uid = random.randint(0, 10000)
            args = node.iterable.args
            if len(args) == 1:
                start_val = ir.Constant(self.int32, 0)
                end_val = self.visit(args[0])
            elif len(args) >= 2:
                start_val = self.visit(args[0])
                end_val = self.visit(args[1])
            else:
                return None
            i_ptr = self._alloca(f"_forin_i_{uid}")
            self.builder.store(start_val, i_ptr)
            scope = self._get_scope()
            scope[node.var_name] = i_ptr
            cond_bb = self.builder.append_basic_block(name="forin.cond")
            body_bb = self.builder.append_basic_block(name="forin.body")
            after_bb = self.builder.append_basic_block(name="forin.after")
            self.loop_stack.append((cond_bb, after_bb))
            self.builder.branch(cond_bb)
            self.builder.position_at_end(cond_bb)
            curr_i = self.builder.load(i_ptr, name="forin_load")
            cmp = self.builder.icmp_signed('<', curr_i, end_val, name="forin_check")
            self.builder.cbranch(cmp, body_bb, after_bb)
            self.builder.position_at_end(body_bb)
            for stmt in node.body:
                self.visit(stmt)
            curr_i_body = self.builder.load(i_ptr)
            next_i = self.builder.add(curr_i_body, ir.Constant(self.int32, 1), name="forin_inc")
            self.builder.store(next_i, i_ptr)
            self.builder.branch(cond_bb)
            self.builder.position_at_end(after_bb)
            self.loop_stack.pop()
        else:
            print(f"Warning: LLVM ForIn only supports range() iteration, skipping.")
            return None

    def visit_PropertyAccess(self, node: PropertyAccess):
        return ir.Constant(self.int32, 0)

    def visit_IndexAccess(self, node: IndexAccess):
        return ir.Constant(self.int32, 0)

    def visit_ListVal(self, node: ListVal):
        return self.builder.call(self.malloc, [ir.Constant(self.int32, 1024)])

    def visit_Dictionary(self, node: Dictionary):
        return self.builder.call(self.malloc, [ir.Constant(self.int32, 1024)])

    def visit_MethodCall(self, node: MethodCall):
        return ir.Constant(self.int32, 0)

    def visit_Instantiation(self, node: Instantiation):
        return self.builder.call(self.malloc, [ir.Constant(self.int32, 1024)])

    def visit_ClassDef(self, node: ClassDef):
        return None