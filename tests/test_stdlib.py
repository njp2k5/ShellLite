"""
Unit tests for ShellLite built-in/stdlib behavior.
"""
import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shell_lite.interpreter import Interpreter
from shell_lite.lexer import Lexer
from shell_lite.parser import Parser


class TestStdLib(unittest.TestCase):
    """Test suite for built-in functions exposed by the interpreter."""

    def run_code(self, code: str):
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast_nodes = parser.parse()
        interpreter = Interpreter()
        last_val = None
        for node in ast_nodes:
            last_val = interpreter.visit(node)
        return interpreter.global_env, last_val, interpreter

    def test_builtin_value_functions(self):
        cases = [
            ("items_len = len([1, 2, 3])", "items_len", 3),
            ("kind = typeof(123)", "kind", "int"),
            ("magnitude = abs(0 - 9)", "magnitude", 9),
            ("text = str(42)", "text", "42"),
            ("whole = int(7.8)", "whole", 7),
        ]

        for code, variable, expected in cases:
            with self.subTest(code=code):
                env, _, _ = self.run_code(code)
                self.assertEqual(env.get(variable), expected)

    def test_print_function(self):
        buffer = StringIO()
        with redirect_stdout(buffer):
            _, last_val, _ = self.run_code('say "Hello ShellLite"')

        self.assertEqual(buffer.getvalue(), "Hello ShellLite\n")
        self.assertEqual(last_val, "Hello ShellLite")

    def test_input_function(self):
        with patch('builtins.input', return_value='ShellLite User') as mocked_input:
            env, _, _ = self.run_code('user_name = ask "Your name? "')

        self.assertEqual(env.get('user_name'), 'ShellLite User')
        mocked_input.assert_called_once_with('Your name? ')


if __name__ == '__main__':
    unittest.main()