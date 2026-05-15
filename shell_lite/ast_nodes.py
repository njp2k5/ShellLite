from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Node:
    """
    -----Purpose: Base class for all Abstract Syntax Tree nodes.
    """
    line: int = field(default=0, init=False)
    col: int = field(default=0, init=False)
    end_line: int = field(default=0, init=False)
    end_col: int = field(default=0, init=False)
@dataclass
class Number(Node):
    """
    -----Purpose: Represents a numeric literal (int or float).
    """
    value: int
@dataclass
class String(Node):
    """
    -----Purpose: Represents a string literal.
    """
    value: str
@dataclass
class Regex(Node):
    """
    -----Purpose: Represents a regular expression literal.
    """
    pattern: str
@dataclass
class VarAccess(Node):
    """
    -----Purpose: Represents an access to a variable by name.
    """
    name: str
@dataclass
class Assign(Node):
    """
    -----Purpose: Represents a variable assignment.
    """
    name: str
    value: Node
@dataclass
class TypedAssign(Node):
    """
    -----Purpose: Represents a typed variable assignment
    """
    name: str
    type_hint: str
    value: Node
@dataclass
class PropertyAssign(Node):
    """
    -----Purpose: Represents an assignment to an object property.
    """
    instance_name: str
    property_name: str
    value: Node
@dataclass
class UnaryOp(Node):
    """
    -----Purpose: Represents a unary operation (e.g., NOT).
    """
    op: str
    right: Node
@dataclass
class BinOp(Node):
    """
    -----Purpose: Represents a binary operation (e.g., +, -, *, /).
    """
    left: Node
    op: str
    right: Node
@dataclass
class Print(Node):
    """
    -----Purpose: Represents a print/say statement.
    """
    expression: Node
    style: Optional[str] = None
    color: Optional[str] = None
@dataclass
class If(Node):
    """
    -----Purpose: Represents a conditional branch (if/elif/else).
    """
    condition: Node
    body: List[Node]
    else_body: Optional[List[Node]] = None
@dataclass
class While(Node):
    """
    -----Purpose: Represents a while loop.
    """
    condition: Node
    body: List[Node]
@dataclass
class For(Node):
    """
    -----Purpose: Represents a numeric for loop.
    """
    count: Node
    body: List[Node]
@dataclass
class ListVal(Node):
    """
    -----Purpose: Represents a list/array literal.
    """
    elements: List[Node]
@dataclass
class Dictionary(Node):
    """
    -----Purpose: Represents a dictionary/map literal.
    """
    pairs: List[tuple[Node, Node]]
@dataclass
class SetVal(Node):
    """
    -----Purpose: Represents a set literal.
    """
    elements: List[Node]
@dataclass
class Boolean(Node):
    """
    -----Purpose: Represents a boolean literal (yes/no).
    """
    value: bool
@dataclass
class Input(Node):
    """
    -----Purpose: Represents a user input request.
    """
    prompt: Optional[str] = None
@dataclass
class FunctionDef(Node):
    """
    -----Purpose: Represents a function/method definition.
    """
    name: str
    args: List[tuple[str, Optional[Node], Optional[str]]]
    body: List[Node]
    return_type: Optional[str] = None
@dataclass
class Call(Node):
    """
    -----Purpose: Represents a function or method call.
    """
    name: str
    args: List[Node]
    kwargs: Optional[List[tuple[str, Node]]] = None
    body: Optional[List[Node]] = None
@dataclass
class Return(Node):
    """
    -----Purpose: Represents a return statement.
    """
    value: Node
@dataclass
class ClassDef(Node):
    """
    -----Purpose: Represents a structure/class definition.
    """
    name: str
    properties: List[tuple[str, Optional[Node]]]
    methods: List[FunctionDef]
    parent: Optional[str] = None
@dataclass
class Instantiation(Node):
    """
    -----Purpose: Represents the creation of a new structure instance.
    """
    var_name: str
    class_name: str
    args: List[Node]
    kwargs: Optional[List[tuple[str, Node]]] = None
@dataclass
class MethodCall(Node):
    """
    -----Purpose: Represents a call to a method on an instance.
    """
    instance_name: str
    method_name: str
    args: List[Node]
    kwargs: Optional[List[tuple[str, Node]]] = None
@dataclass
class PropertyAccess(Node):
    """
    -----Purpose: Represents an access to an object property.
    """
    instance_name: str
    property_name: str
@dataclass
class Import(Node):
    """
    -----Purpose: Represents an import statement.
    """
    path: str
@dataclass
class Try(Node):
    """
    -----Purpose: Represents a try-catch block.
    """
    try_body: List[Node]
    catch_var: str
    catch_body: List[Node]
@dataclass
class Match(Node):
    """
    -----Purpose: Represents a pattern matching switch block.
    """
    match_expr: Node
    cases: List[tuple[Node, List[Node]]]
    default_case: Optional[List[Node]] = None
@dataclass
class Lambda(Node):
    """
    -----Purpose: Represents an anonymous function.
    """
    params: List[str]
    body: Node
@dataclass
class Ternary(Node):
    """
    -----Purpose: Represents a ternary conditional expression.
    """
    condition: Node
    true_expr: Node
    false_expr: Node
@dataclass
class ListComprehension(Node):
    """
    -----Purpose: Represents a list comprehension expression.
    """
    expr: Node
    var_name: str
    iterable: Node
    condition: Optional[Node] = None
@dataclass
class Spread(Node):
    """
    -----Purpose: Represents the spread operator (...) for lists.
    """
    value: Node
@dataclass
class ConstAssign(Node):
    """
    -----Purpose: Represents a constant assignment (immutable).
    """
    name: str
    value: Node
@dataclass
class ForIn(Node):
    """
    -----Purpose: Represents a for-in collection iteration loop.
    """
    var_name: str
    iterable: Node
    body: List[Node]
@dataclass
class IndexAccess(Node):
    """
    -----Purpose: Represents an index access (e.g., list[0]).
    """
    obj: Node
    index: Node
@dataclass
class IndexAssign(Node):
    """
    -----Purpose: Represents an assignment to a list index or dictionary key.
    """
    obj: Node
    index: Node
    value: Node
@dataclass
class Stop(Node):
    """
    -----Purpose: Represents a 'stop' (break) statement.
    """
    pass
@dataclass
class Skip(Node):
    """
    -----Purpose: Represents a 'skip' (continue) statement.
    """
    pass
@dataclass
class When(Node):
    """
    -----Purpose: Represents a 'when' (switch/match) branch statement.
    """
    value: Node
    cases: List[tuple[Node, List[Node]]]
    otherwise: Optional[List[Node]] = None
@dataclass
class Throw(Node):
    """
    -----Purpose: Represents an 'error' (throw) statement.
    """
    message: Node
@dataclass
class TryAlways(Node):
    """
    -----Purpose: Represents a try-catch-always block.
    """
    try_body: List[Node]
    catch_var: str
    catch_body: List[Node]
    always_body: List[Node]
@dataclass
class Unless(Node):
    """
    -----Purpose: Represents an 'unless' (inverted if) conditional.
    """
    condition: Node
    body: List[Node]
    else_body: Optional[List[Node]] = None
@dataclass
class Execute(Node):
    """
    -----Purpose: Represents a dynamic 'execute' (eval) statement.
    """
    code: Node
@dataclass
class Repeat(Node):
    """
    -----Purpose: Represents a 'repeat N times' loop.
    """
    count: Node
    body: List[Node]
@dataclass
class ImportAs(Node):
    """
    -----Purpose: Represents an 'import as' statement with aliasing.
    """
    path: str
    alias: str
@dataclass
class Until(Node):
    """
    -----Purpose: Represents an 'until' loop (inverted while).
    """
    condition: Node
    body: List[Node]
@dataclass
class Forever(Node):
    """
    -----Purpose: Represents an infinite 'forever' loop.
    """
    body: List[Node]
@dataclass
class Exit(Node):
    """
    -----Purpose: Represents an 'exit' statement.
    """
    code: Optional[Node] = None
@dataclass
class Make(Node):
    """
    -----Purpose: Represents a 'make' (instantiation) expression.
    """
    class_name: str
    args: List[Node]
@dataclass
class FileWatcher(Node):
    """
    -----Purpose: Represents a file system watcher block.
    """
    path: Node
    body: List[Node]
@dataclass
class Alert(Node):
    """
    -----Purpose: Represents a GUI alert statement.
    """
    message: Node
@dataclass
class Prompt(Node):
    """
    -----Purpose: Represents a GUI prompt statement.
    """
    prompt: Node
@dataclass
class Confirm(Node):
    """
    -----Purpose: Represents a GUI confirm statement.
    """
    prompt: Node
@dataclass
class Spawn(Node):
    """
    -----Purpose: Represents an asynchronous 'spawn' statement.
    """
    call: Node
@dataclass
class Await(Node):
    """
    -----Purpose: Represents an 'await' statement for async tasks.
    """
    task: Node
@dataclass
class ProgressLoop(Node):
    """
    -----Purpose: Represents a decorated loop with a progress bar.
    """
    loop_node: Node
@dataclass
class Convert(Node):
    """
    -----Purpose: Represents a data conversion expression.
    """
    expression: Node
    target_format: str
@dataclass
class Listen(Node):
    """
    -----Purpose: Represents a network 'listen' statement.
    """
    port: Node
@dataclass
class OnRequest(Node):
    """
    -----Purpose: Represents a network request handler block.
    """
    path: Node
    body: List[Node]
@dataclass
class Every(Node):
    """
    -----Purpose: Represents a scheduled 'every' interval task.
    """
    interval: Node
    unit: str
    body: List[Node]
@dataclass
class After(Node):
    """
    -----Purpose: Represents a scheduled 'after' delayed task.
    """
    delay: Node
    unit: str
    body: List[Node]
@dataclass
class ServeStatic(Node):
    """
    -----Purpose: Represents a static file server configuration.
    """
    folder: Node
    url: Node
@dataclass
class Download(Node):
    """
    -----Purpose: Represents a file download operation.
    """
    url: Node
@dataclass
class ArchiveOp(Node):
    """
    -----Purpose: Represents an archive operation (compress/extract).
    """
    op: str
    source: Node
    target: Node
@dataclass
class CsvOp(Node):
    """
    -----Purpose: Represents a CSV data operation (load/save).
    """
    op: str
    data: Optional[Node]
    path: Node
@dataclass
class ClipboardOp(Node):
    """
    -----Purpose: Represents a clipboard operation (copy/paste).
    """
    op: str
    content: Optional[Node]
@dataclass
class AutomationOp(Node):
    """
    -----Purpose: Represents a GUI automation operation (click/type/press).
    """
    action: str
    args: List[Node]
@dataclass
class DateOp(Node):
    """
    -----Purpose: Represents a date formatting or retrieval operation.
    """
    expr: str
@dataclass
class FileWrite(Node):
    """
    -----Purpose: Represents a file write/append operation.
    """
    path: Node
    content: Node
    mode: str
@dataclass
class FileRead(Node):
    """
    -----Purpose: Represents a file read operation.
    """
    path: Node
@dataclass
class DatabaseOp(Node):
    """
    -----Purpose: Represents a database operation (open/query/exec).
    """
    op: str
    args: List[Node]
@dataclass
class PythonImport(Node):
    """
    -----Purpose: Represents a native Python module import.
    """
    module_name: str
    alias: Optional[str]
@dataclass
class FromImport(Node):
    """
    -----Purpose: Represents a selective module import (from...import).
    """
    module_name: str
    names: List[tuple[str, Optional[str]]]
@dataclass
class App(Node):
    """
    -----Purpose: Represents a main GUI application container.
    """
    title: str
    width: int
    height: int
    body: List[Node]
@dataclass
class Widget(Node):
    """
    -----Purpose: Represents a generic GUI widget (button/input/etc).
    """
    widget_type: str
    label: str
    var_name: Optional[str] = None
    event_handler: Optional[List[Node]] = None
@dataclass
class Layout(Node):
    """
    -----Purpose: Represents a GUI layout container (row/column).
    """
    layout_type: str
    body: List[Node]
@dataclass
class TestBlock(Node):
    """
    -----Purpose: Represents a testing block ('test "name"').
    """
    name: str
    body: List[Node]
@dataclass
class Assertion(Node):
    """
    -----Purpose: Represents a test assertion ('expect x to be y').
    """
    left: Node
    op: str
    right: Optional[Node] = None

@dataclass
class Parallel(Node):
    """
    -----Purpose: Represents a 'parallel' block that runs children concurrently.
    """
    body: List[Node]
@dataclass
class Gather(Node):
    """
    -----Purpose: Represents a 'gather' expression that awaits all futures.
    """
    tasks: Node
@dataclass
class Lock(Node):
    """
    -----Purpose: Represents a 'lock' block with a named mutex.
    """
    name: str
    body: List[Node]
@dataclass
class Channel(Node):
    """
    -----Purpose: Represents a channel constructor expression.
    """
    pass
@dataclass
class Send(Node):
    """
    -----Purpose: Represents a 'send' statement to push a value into a channel.
    """
    channel: Node
    value: Node
@dataclass
class Receive(Node):
    """
    -----Purpose: Represents a 'receive' expression to pull a value from a channel.
    """
    channel: Node

@dataclass
class ModelDef(Node):
    """
    -----Purpose: Represents an ORM model definition.
    """
    name: str
    fields: List[tuple]
@dataclass
class CreateTable(Node):
    """
    -----Purpose: Represents a 'create table' statement from a model.
    """
    model_name: str
@dataclass
class InsertRecord(Node):
    """
    -----Purpose: Represents an 'insert' statement into a model table.
    """
    model_name: str
    values: List[tuple]
@dataclass
class FindRecords(Node):
    """
    -----Purpose: Represents a 'find' query on a model table.
    """
    model_name: str
    conditions: List[tuple]
    find_all: bool = True
    is_count: bool = False
@dataclass
class UpdateRecords(Node):
    """
    -----Purpose: Represents an 'update' statement on a model table.
    """
    model_name: str
    conditions: List[tuple]
    updates: List[tuple]
@dataclass
class DeleteRecords(Node):
    """
    -----Purpose: Represents a 'delete' statement on a model table.
    """
    model_name: str
    conditions: List[tuple]
@dataclass
class MaxNode(Node):
    """
    -----Purpose: Represents a 'maximum of a and b' or 'maximum of list' expression.
    """
    left: Node
    right: Optional[Node] = None

@dataclass
class MinNode(Node):
    """
    -----Purpose: Represents a 'minimum of a and b' or 'minimum of list' expression.
    """
    left: Node
    right: Optional[Node] = None

@dataclass
class ClampNode(Node):
    """
    -----Purpose: Represents a 'clamped X between min and max' expression.
    """
    value: Node
    min_val: Node
    max_val: Node

@dataclass
class LerpNode(Node):
    """
    -----Purpose: Represents a 'lerp from A to B by T' expression.
    """
    start: Node
    end: Node
    alpha: Node
