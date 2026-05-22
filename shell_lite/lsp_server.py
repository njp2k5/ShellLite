# Language Server Protocol (LSP) server implementation for the ShellLite IDE integration.
import json
import logging
import sys
from typing import Any, Dict, List, Optional

logging.basicConfig(filename="shell_lite_lsp.log", level=logging.DEBUG, filemode="w")
logger = logging.getLogger("LSP")

from .ast_nodes import Assign, ClassDef, FunctionDef, Node, TypedAssign, VarAccess
from .lexer import Lexer
from .parser import Parser


class SymbolKind:
    File = 1
    Module = 2
    Namespace = 3
    Package = 4
    Class = 5
    Method = 6
    Property = 7
    Field = 8
    Constructor = 9
    Enum = 10
    Interface = 11
    Function = 12
    Variable = 13
    Constant = 14
    String = 15
    Number = 16
    Boolean = 17
    Array = 18
    Object = 19
    Key = 20
    Null = 21
    EnumMember = 22
    Struct = 23
    Event = 24
    Operator = 25
    TypeParameter = 26

_KEYWORDS = [
    "if", "elif", "else", "while", "until", "unless", "forever",
    "repeat", "times", "for", "in", "to", "give", "say", "print",
    "test", "expect", "ensure", "thing", "has", "can", "use", "import",
    "from", "as", "try", "catch", "always", "error", "spawn", "await",
    "every", "after", "stop", "skip", "yes", "no", "and", "or", "not",
    "is", "be", "more", "less", "than", "equal", "int", "str", "float",
    "bool", "list", "dict", "string", "integer", "decimal",
]

class ShellLiteDocument:
    def __init__(self, uri: str, text: str):
        self.uri = uri
        self.text = text
        self.lines = text.splitlines(keepends=True)
        self.ast_nodes: List[Node] = []
        self.diagnostics: List[dict] = []
        self.symbols: List[dict] = []
        self.parse_and_analyze()

    def update(self, text: str):
        self.text = text
        self.lines = text.splitlines(keepends=True)
        self.parse_and_analyze()

    def parse_and_analyze(self):
        self.diagnostics = []
        self.symbols = []
        try:
            lexer = Lexer(self.text)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            self.ast_nodes = parser.parse()
        except SyntaxError as e:
            line = max((getattr(e, "lineno", 1) or 1) - 1, 0)
            self.diagnostics.append({
                "range": {
                    "start": {"line": line, "character": 0},
                    "end":   {"line": line, "character": 999},
                },
                "severity": 1,
                "source": "ShellLite (Parser)",
                "message": str(e),
            })
            return
        except Exception as e:
            logger.error(f"Parser error: {e}")
            self.diagnostics.append({
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end":   {"line": 0, "character": 999},
                },
                "severity": 1,
                "source": "ShellLite (System)",
                "message": f"Parser crash: {e}",
            })
            return

        logger.debug(f"Parsed {len(self.ast_nodes)} nodes")
        for n in self.ast_nodes:
            logger.debug(f" - Node: {type(n).__name__} line={n.line} col={n.col} end={n.end_line}:{n.end_col}")

        self._collect_symbols_and_semantic_checks()

    def _collect_symbols_and_semantic_checks(self):
        defined_names = {}
        
        def walk(nodes):
            for node in nodes:
                if isinstance(node, FunctionDef):
                    self.symbols.append({
                        "name": node.name,
                        "kind": SymbolKind.Function,
                        "range": self._node_to_range(node),
                        "selectionRange": self._node_to_range(node),
                        "children": []
                    })
                    if node.name in defined_names:
                        self.diagnostics.append({
                            "range": self._node_to_range(node),
                            "severity": 2, # Warning
                            "message": f"Redefinition of function '{node.name}' (first defined at line {defined_names[node.name]+1})"
                        })
                    defined_names[node.name] = node.line
                
                elif isinstance(node, (Assign, TypedAssign)):
                    self.symbols.append({
                        "name": node.name,
                        "kind": SymbolKind.Variable,
                        "range": self._node_to_range(node),
                        "selectionRange": self._node_to_range(node),
                    })
                
                elif isinstance(node, ClassDef):
                    self.symbols.append({
                        "name": node.name,
                        "kind": SymbolKind.Struct,
                        "range": self._node_to_range(node),
                        "selectionRange": self._node_to_range(node),
                    })

                if hasattr(node, 'body') and isinstance(node.body, list):
                    walk(node.body)
                if hasattr(node, 'else_body') and isinstance(node.else_body, list):
                    walk(node.else_body)

        walk(self.ast_nodes)

    def _node_to_range(self, node: Node) -> dict:
        return {
            "start": {"line": max(node.line - 1, 0), "character": max(node.col - 1, 0)},
            "end":   {"line": max(node.end_line - 1, node.line - 1, 0), "character": max(node.end_col - 1, 0) if node.end_col != 999 else 999},
        }

    def get_formatting(self) -> List[dict]:
        formatted_lines = []
        indent_level = 0
        for line in self.lines:
            stripped = line.lstrip()
            if not stripped:
                formatted_lines.append("\n")
                continue
            
            if stripped.startswith(("end", "else", "elif", "catch", "always")):
                indent_level = max(0, indent_level - 1)
            
            formatted_lines.append("    " * indent_level + stripped)

            if stripped.strip().endswith(":") or stripped.startswith(("if ", "while ", "for ", "to ", "thing ", "test ")):
                if not stripped.startswith(("end", "give", "return", "stop", "skip")):
                    indent_level += 1
                    
        new_text = "".join(formatted_lines)
        if new_text == self.text:
            return []
            
        return [{
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": len(self.lines), "character": 0}
            },
            "newText": new_text
        }]
class LSPServer:
    def __init__(self):
        self._documents: Dict[str, ShellLiteDocument] = {}
        self._running = True

    def _read_message(self, stream) -> dict | None:
        headers = {}
        while True:
            line = stream.readline()
            if not line: return None
            line = line.decode("utf-8").rstrip("\r\n")
            if not line: break
            if ":" in line:
                key, _, val = line.partition(":")
                headers[key.strip().lower()] = val.strip()
        length = int(headers.get("content-length", 0))
        if length == 0: return None
        body = stream.read(length).decode("utf-8")
        return json.loads(body)

    def _write_message(self, stream, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        stream.write(header + body)
        stream.flush()

    def _notify(self, method: str, params: Any):
        self._write_message(sys.stdout.buffer, {"jsonrpc": "2.0", "method": method, "params": params})

    def _respond(self, req_id: Any, result: Any):
        self._write_message(sys.stdout.buffer, {"jsonrpc": "2.0", "id": req_id, "result": result})

    def _publish_diagnostics(self, doc: ShellLiteDocument):
        self._notify("textDocument/publishDiagnostics", {
            "uri": doc.uri,
            "diagnostics": doc.diagnostics
        })

    def run(self):
        stdin = sys.stdin.buffer
        while self._running:
            try:
                msg = self._read_message(stdin)
                if msg is None: break
                self._handle_message(msg)
            except Exception as e:
                break

    def _handle_message(self, msg: dict):
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params", {})

        if not method and req_id is not None: return

        if method == "initialize":
            self._respond(req_id, {
                "capabilities": {
                    "textDocumentSync": 1,
                    "hoverProvider": True,
                    "completionProvider": {"triggerCharacters": [" ", "."]},
                    "definitionProvider": True,
                    "documentSymbolProvider": True,
                    "documentFormattingProvider": True,
                    "renameProvider": True,
                    "referencesProvider": True,
                },
                "serverInfo": {"name": "ShellLite Enhanced LSP", "version": "0.6.1.1"},
            })
        elif method == "textDocument/didOpen":
            uri = params["textDocument"]["uri"]
            text = params["textDocument"]["text"]
            doc = ShellLiteDocument(uri, text)
            self._documents[uri] = doc
            self._publish_diagnostics(doc)
        elif method == "textDocument/didChange":
            uri = params["textDocument"]["uri"]
            text = params["contentChanges"][-1]["text"]
            if uri in self._documents:
                doc = self._documents[uri]
                doc.update(text)
                self._publish_diagnostics(doc)
        elif method == "textDocument/hover":
            self._handle_hover(req_id, params)
        elif method == "textDocument/documentSymbol":
            uri = params["textDocument"]["uri"]
            doc = self._documents.get(uri)
            self._respond(req_id, doc.symbols if doc else [])
        elif method == "textDocument/formatting":
            uri = params["textDocument"]["uri"]
            doc = self._documents.get(uri)
            self._respond(req_id, doc.get_formatting() if doc else [])
        elif method == "textDocument/definition":
            self._handle_definition(req_id, params)
        elif method == "textDocument/completion":
            self._handle_completion(req_id, params)
        elif method == "textDocument/rename":
            self._handle_rename(req_id, params)
        elif method == "textDocument/references":
            self._handle_references(req_id, params)
        elif method == "shutdown":
            self._respond(req_id, None)
        elif method == "exit":
            self._running = False

    def _find_node_at(self, doc: ShellLiteDocument, line: int, char: int) -> Optional[Node]:
        best_node = None
        min_width = 999999
        
        def walk(nodes):
            nonlocal best_node, min_width
            for node in nodes:
                start_l = node.line - 1
                end_l = max(node.end_line - 1, start_l)
                start_c = max(node.col - 1, 0)
                end_c = max(node.end_col - 1, start_c) if node.end_col != 999 else 999
                
                in_range = False
                if start_l <= line <= end_l:
                    if start_l == line == end_l:
                        in_range = start_c <= char <= end_c
                    elif line == start_l:
                        in_range = char >= start_c
                    elif line == end_l:
                        in_range = char <= end_c
                    else:
                        in_range = True
                
                if in_range:
                    width = (end_l - start_l) * 1000 + (end_c - start_c)
                    if width <= min_width:
                        best_node = node
                        min_width = width
                        logger.debug(f"Found candidate node: {type(node).__name__} at {start_l}:{start_c}-{end_l}:{end_c} width={width}")
                
                for attr in ['body', 'else_body', 'expression', 'value', 'condition', 'args', 'elements']:
                    child = getattr(node, attr, None)
                    if isinstance(child, list): walk(child)
                    elif isinstance(child, Node): walk([child])
        
        walk(doc.ast_nodes)
        return best_node

    def _handle_hover(self, req_id, params):
        uri = params["textDocument"]["uri"]
        pos = params["position"]
        doc = self._documents.get(uri)
        if not doc: return self._respond(req_id, None)

        node = self._find_node_at(doc, pos["line"], pos["character"])
        if not node:
            word = self._get_word_at(doc, pos["line"], pos["character"])
            if word in _KEYWORDS:
                return self._respond(req_id, {"contents": {"kind": "markdown", "value": f"**keyword** `{word}`"}})
            return self._respond(req_id, None)

        content = ""
        if isinstance(node, FunctionDef):
            args_str = ", ".join([f"{a[0]}" + (f" as {a[2]}" if a[2] else "") for a in node.args])
            content = f"**function** `{node.name}({args_str})`"
        elif isinstance(node, Assign):
            content = f"**variable** `{node.name}`"
        elif isinstance(node, TypedAssign):
            content = f"**variable** `{node.name}`\n\n*Type: {node.type_hint}*"
        elif isinstance(node, VarAccess):
            content = f"**access** variable `{node.name}`"
        elif isinstance(node, ClassDef):
            content = f"**thing** (class) `{node.name}`"

        if content:
            self._respond(req_id, {"contents": {"kind": "markdown", "value": content}})
        else:
            self._respond(req_id, None)

    def _handle_definition(self, req_id, params):
        uri = params["textDocument"]["uri"]
        pos = params["position"]
        doc = self._documents.get(uri)
        if not doc: return self._respond(req_id, None)

        node = self._find_node_at(doc, pos["line"], pos["character"])
        name = getattr(node, 'name', None) or getattr(node, 'class_name', None)
        if not name and isinstance(node, VarAccess):
            name = node.name

        if not name: return self._respond(req_id, None)

        for sym in doc.symbols:
            if sym["name"] == name:
                return self._respond(req_id, {"uri": uri, "range": sym["range"]})
        
        self._respond(req_id, None)

    def _handle_completion(self, req_id, params):
        uri = params["textDocument"]["uri"]
        doc = self._documents.get(uri)
        items = []
        seen = set()
        
        if doc:
            for sym in doc.symbols:
                if sym["name"] not in seen:
                    items.append({"label": sym["name"], "kind": sym["kind"]})
                    seen.add(sym["name"])
        
        for kw in _KEYWORDS:
            if kw not in seen:
                items.append({"label": kw, "kind": 14})
                
        self._respond(req_id, {"isIncomplete": False, "items": items})

    def _handle_rename(self, req_id, params):
        uri = params["textDocument"]["uri"]
        pos = params["position"]
        new_name = params["newName"]
        doc = self._documents.get(uri)
        if not doc: return self._respond(req_id, None)

        node = self._find_node_at(doc, pos["line"], pos["character"])
        logger.debug(f"Rename request at {pos['line']}:{pos['character']} found node: {type(node).__name__ if node else 'None'}")
        
        old_name = getattr(node, 'name', None) or (node.name if isinstance(node, VarAccess) else None)
        logger.debug(f"Old name identified: {old_name}")
        
        if not old_name: return self._respond(req_id, None)

        edits = []
        def walk(nodes):
            for n in nodes:
                if (isinstance(n, (Assign, TypedAssign, FunctionDef, ClassDef, VarAccess)) and 
                    getattr(n, "name", None) == old_name):
                    edits.append({
                        "range": {
                            "start": {"line": n.line - 1, "character": max(n.col - 1, 0)},
                            "end": {"line": n.line - 1, "character": max(n.col - 1 + len(old_name), 0)}
                        },
                        "newText": new_name
                    })
                for attr in ['body', 'else_body', 'expression', 'value', 'condition', 'args', 'elements']:
                    child = getattr(n, attr, None)
                    if isinstance(child, list): walk(child)
                    elif isinstance(child, Node): walk([child])

        walk(doc.ast_nodes)
        self._respond(req_id, {"changes": {uri: edits}})

    def _handle_references(self, req_id, params):
        uri = params["textDocument"]["uri"]
        pos = params["position"]
        doc = self._documents.get(uri)
        if not doc: return self._respond(req_id, None)

        node = self._find_node_at(doc, pos["line"], pos["character"])
        name = getattr(node, 'name', None) or (node.name if isinstance(node, VarAccess) else None)
        if not name: return self._respond(req_id, None)

        refs = []
        def walk(nodes):
            for n in nodes:
                if (isinstance(n, (Assign, TypedAssign, FunctionDef, ClassDef, VarAccess)) and 
                    getattr(n, "name", None) == name):
                    refs.append({
                        "uri": uri,
                        "range": {
                            "start": {"line": n.line - 1, "character": max(n.col - 1, 0)},
                            "end": {"line": n.line - 1, "character": max(n.col - 1 + len(name), 0)}
                        }
                    })
                for attr in ['body', 'else_body', 'expression', 'value', 'condition', 'args', 'elements']:
                    child = getattr(n, attr, None)
                    if isinstance(child, list): walk(child)
                    elif isinstance(child, Node): walk([child])

        walk(doc.ast_nodes)
        self._respond(req_id, refs)

    def _get_word_at(self, doc: ShellLiteDocument, line: int, char: int) -> str:
        if line >= len(doc.lines): return ""
        text = doc.lines[line]
        start = char
        while start > 0 and (text[start-1].isalnum() or text[start-1] == '_'):
            start -= 1
        end = char
        while end < len(text) and (text[end].isalnum() or text[end] == '_'):
            end += 1
        return text[start:end]

def run_lsp():
    server = LSPServer()
    server.run()
