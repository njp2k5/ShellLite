import os

from ..lexer import Lexer
from ..parser_gbp import GeometricBindingParser as Parser
from .codegen import LLVMCompiler


def build_llvm(filename: str):
    """
    -----Purpose: Main entry point for the LLVM compilation pipeline. 
    -----        Reads source, tokenizes, parses, and generates LLVM IR.
    """
    print(f"Compiling {filename} with LLVM Backend...")
    with open(filename, 'r', encoding='utf-8') as f:
        source = f.read()
    
    lexer = Lexer(source)
    tokens = lexer.tokenize()
    parser = Parser(tokens)
    statements = parser.parse()
    
    compiler = LLVMCompiler(base_path=os.path.dirname(os.path.abspath(filename)), filename=os.path.basename(filename))
    is_entry = os.path.basename(filename) in ["main.shl", "test.shl", "simple_main.shl", "clean_main.shl"]
    module = compiler.compile(statements, is_entry_point=is_entry)
    llvm_ir = str(module)
    
    print("\n--- Generated LLVM IR ---")
    print(llvm_ir)
    print("-------------------------\n")
    
    ll_filename = os.path.splitext(filename)[0] + ".ll"
    with open(ll_filename, 'w') as f:
        f.write(llvm_ir)
    
    print(f"[SUCCESS] Generated LLVM IR: {ll_filename}")
    print("\nTo compile to executable, use Clang:")
    import sys as _sys
    exe_ext = '.exe' if _sys.platform == 'win32' else ''
    exe_name = os.path.splitext(filename)[0] + exe_ext
    print(f"  clang {ll_filename} -o {exe_name}")
    if _sys.platform != 'win32':
        print(f"  chmod +x {exe_name}")