from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult


SUPPORTED_LSP_OPERATIONS = {
    "goToDefinition",
    "findReferences",
    "hover",
    "documentSymbol",
    "workspaceSymbol",
    "goToImplementation",
    "prepareCallHierarchy",
    "incomingCalls",
    "outgoingCalls",
}
SUPPORTED_SYMBOL_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"}


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    name: str
    kind: str
    path: Path
    line: int
    character: int
    container: str | None = None
    doc: str = ""
    outgoing_calls: tuple[str, ...] = ()
    end_line: int | None = None
    end_character: int | None = None


@dataclass(slots=True)
class LSPInput:
    operation: str
    file_path: str | None = None
    line: int = 1
    character: int = 1
    query: str = ""
    symbol: str = ""
    max_results: int = 20


class LSPTool(BaseTool[LSPInput]):
    name = "LSP"
    description = "Interact with a lightweight language-intelligence layer for definitions, references, hover, and symbol search"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": sorted(SUPPORTED_LSP_OPERATIONS)},
                "filePath": {"type": "string"},
                "file_path": {"type": "string"},
                "line": {"type": "integer", "minimum": 1},
                "character": {"type": "integer", "minimum": 1},
                "query": {"type": "string"},
                "symbol": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["operation"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> LSPInput:
        operation = raw_input.get("operation")
        file_path = raw_input.get("filePath", raw_input.get("file_path"))
        line = raw_input.get("line", 1)
        character = raw_input.get("character", 1)
        query = raw_input.get("query", "")
        symbol = raw_input.get("symbol", "")
        max_results = raw_input.get("max_results", 20)
        if not isinstance(operation, str) or operation not in SUPPORTED_LSP_OPERATIONS:
            raise ValueError("operation must be a supported LSP operation")
        if file_path is not None and not isinstance(file_path, str):
            raise ValueError("file_path must be a string")
        if not isinstance(line, int) or line <= 0:
            raise ValueError("line must be a positive integer")
        if not isinstance(character, int) or character <= 0:
            raise ValueError("character must be a positive integer")
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        if not isinstance(symbol, str):
            raise ValueError("symbol must be a string")
        if not isinstance(max_results, int) or not (1 <= max_results <= 100):
            raise ValueError("max_results must be between 1 and 100")
        return LSPInput(
            operation=operation,
            file_path=file_path.strip() if isinstance(file_path, str) and file_path.strip() else None,
            line=line,
            character=character,
            query=query.strip(),
            symbol=symbol.strip(),
            max_results=max_results,
        )

    def is_read_only(self, parsed_input: LSPInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: LSPInput) -> bool:
        return True

    async def validate(self, parsed_input: LSPInput, context: ToolContext) -> ValidationResult:
        if parsed_input.file_path:
            path = self.resolve_path(context, parsed_input.file_path)
            if not path.exists() or not path.is_file():
                return ValidationResult.failure(f"file not found: {parsed_input.file_path}")
        if parsed_input.operation == "workspaceSymbol" and not parsed_input.query:
            return ValidationResult.failure("query is required for workspaceSymbol")
        if parsed_input.operation in {"goToDefinition", "findReferences", "hover", "goToImplementation", "prepareCallHierarchy", "incomingCalls", "outgoingCalls"} and not parsed_input.file_path:
            return ValidationResult.failure("file_path is required for this operation")
        return ValidationResult.success()

    async def call(self, parsed_input: LSPInput, context: ToolContext) -> ToolResult:
        if parsed_input.operation == "documentSymbol":
            return self._document_symbol(parsed_input, context)
        if parsed_input.operation == "workspaceSymbol":
            return self._workspace_symbol(parsed_input, context)
        if parsed_input.operation == "hover":
            return self._hover(parsed_input, context)
        if parsed_input.operation in {"goToDefinition", "goToImplementation"}:
            return self._go_to_definition(parsed_input, context)
        if parsed_input.operation == "findReferences":
            return self._find_references(parsed_input, context)
        if parsed_input.operation == "prepareCallHierarchy":
            return self._prepare_call_hierarchy(parsed_input, context)
        if parsed_input.operation == "outgoingCalls":
            return self._outgoing_calls(parsed_input, context)
        if parsed_input.operation == "incomingCalls":
            return self._incoming_calls(parsed_input, context)
        return ToolResult(content=f"unsupported operation: {parsed_input.operation}", is_error=True)

    def _document_symbol(self, parsed_input: LSPInput, context: ToolContext) -> ToolResult:
        path = self.resolve_path(context, parsed_input.file_path or "")
        symbols = self._symbols_for_file(path)
        if not symbols:
            return ToolResult(content="No symbols found in document")
        lines = [f"Symbols in {self._display_path(path, context.cwd)}:"]
        for symbol in symbols[: parsed_input.max_results]:
            container = f" ({symbol.container})" if symbol.container else ""
            lines.append(
                f"- {symbol.kind} {symbol.name}{container} @ {self._display_path(symbol.path, context.cwd)}:{symbol.line}:{symbol.character}"
            )
        return ToolResult(content="\n".join(lines))

    def _workspace_symbol(self, parsed_input: LSPInput, context: ToolContext) -> ToolResult:
        matches = [
            symbol
            for symbol in self._workspace_symbols(context.cwd)
            if parsed_input.query.lower() in symbol.name.lower()
        ][: parsed_input.max_results]
        if not matches:
            return ToolResult(content="No workspace symbols found")
        lines = [f'Workspace symbols for "{parsed_input.query}":']
        for symbol in matches:
            lines.append(
                f"- {symbol.kind} {symbol.name} @ {self._display_path(symbol.path, context.cwd)}:{symbol.line}:{symbol.character}"
            )
        return ToolResult(content="\n".join(lines))

    def _hover(self, parsed_input: LSPInput, context: ToolContext) -> ToolResult:
        path = self.resolve_path(context, parsed_input.file_path or "")
        text = path.read_text(encoding="utf-8", errors="replace")
        symbol_name = parsed_input.symbol or self._token_at_position(text, parsed_input.line, parsed_input.character)
        if not symbol_name:
            return ToolResult(content="No symbol found at the requested position", is_error=True)
        definitions = self._find_symbol_definitions(symbol_name, context.cwd)
        current_line = self._line_at(text, parsed_input.line)
        if definitions:
            symbol = definitions[0]
            parts = [
                f"Symbol: {symbol.name}",
                f"Kind: {symbol.kind}",
                f"Definition: {self._display_path(symbol.path, context.cwd)}:{symbol.line}:{symbol.character}",
            ]
            if symbol.doc:
                parts.append(f"Documentation: {symbol.doc}")
            if current_line:
                parts.append(f"Line: {current_line}")
            return ToolResult(content="\n".join(parts))
        return ToolResult(content=f"Symbol: {symbol_name}\nLine: {current_line}".strip())

    def _go_to_definition(self, parsed_input: LSPInput, context: ToolContext) -> ToolResult:
        path = self.resolve_path(context, parsed_input.file_path or "")
        text = path.read_text(encoding="utf-8", errors="replace")
        symbol_name = parsed_input.symbol or self._token_at_position(text, parsed_input.line, parsed_input.character)
        if not symbol_name:
            return ToolResult(content="No symbol found at the requested position", is_error=True)
        definitions = self._find_symbol_definitions(symbol_name, context.cwd)[: parsed_input.max_results]
        if not definitions:
            return ToolResult(content=f"No definition found for {symbol_name}")
        lines = [f"Definitions for {symbol_name}:"]
        for symbol in definitions:
            lines.append(
                f"- {symbol.kind} {symbol.name} @ {self._display_path(symbol.path, context.cwd)}:{symbol.line}:{symbol.character}"
            )
        return ToolResult(content="\n".join(lines))

    def _find_references(self, parsed_input: LSPInput, context: ToolContext) -> ToolResult:
        path = self.resolve_path(context, parsed_input.file_path or "")
        text = path.read_text(encoding="utf-8", errors="replace")
        symbol_name = parsed_input.symbol or self._token_at_position(text, parsed_input.line, parsed_input.character)
        if not symbol_name:
            return ToolResult(content="No symbol found at the requested position", is_error=True)
        pattern = re.compile(rf"\b{re.escape(symbol_name)}\b")
        hits: list[str] = []
        for file_path in self._workspace_files(context.cwd):
            source = file_path.read_text(encoding="utf-8", errors="replace")
            for line_number, line_text in enumerate(source.splitlines(), start=1):
                if pattern.search(line_text):
                    hits.append(
                        f"{self._display_path(file_path, context.cwd)}:{line_number}: {line_text.strip()}"
                    )
                    if len(hits) >= parsed_input.max_results:
                        return ToolResult(content="\n".join([f"References for {symbol_name}:"] + hits))
        if not hits:
            return ToolResult(content=f"No references found for {symbol_name}")
        return ToolResult(content="\n".join([f"References for {symbol_name}:"] + hits))

    def _prepare_call_hierarchy(self, parsed_input: LSPInput, context: ToolContext) -> ToolResult:
        symbol = self._enclosing_symbol(parsed_input, context)
        if symbol is None:
            return ToolResult(content="No callable symbol found at the requested position", is_error=True)
        parts = [
            f"Call hierarchy root: {symbol.name}",
            f"Kind: {symbol.kind}",
            f"Location: {self._display_path(symbol.path, context.cwd)}:{symbol.line}:{symbol.character}",
        ]
        if symbol.outgoing_calls:
            parts.append(f"Outgoing calls: {', '.join(symbol.outgoing_calls)}")
        return ToolResult(content="\n".join(parts))

    def _outgoing_calls(self, parsed_input: LSPInput, context: ToolContext) -> ToolResult:
        symbol = self._enclosing_symbol(parsed_input, context)
        if symbol is None:
            return ToolResult(content="No callable symbol found at the requested position", is_error=True)
        if not symbol.outgoing_calls:
            return ToolResult(content=f"No outgoing calls found for {symbol.name}")
        lines = [f"Outgoing calls from {symbol.name}:"]
        for call_name in symbol.outgoing_calls[: parsed_input.max_results]:
            definitions = self._find_symbol_definitions(call_name, context.cwd)
            if definitions:
                target = definitions[0]
                lines.append(
                    f"- {call_name} -> {self._display_path(target.path, context.cwd)}:{target.line}:{target.character}"
                )
            else:
                lines.append(f"- {call_name}")
        return ToolResult(content="\n".join(lines))

    def _incoming_calls(self, parsed_input: LSPInput, context: ToolContext) -> ToolResult:
        path = self.resolve_path(context, parsed_input.file_path or "")
        text = path.read_text(encoding="utf-8", errors="replace")
        symbol_name = parsed_input.symbol or self._token_at_position(text, parsed_input.line, parsed_input.character)
        if not symbol_name:
            return ToolResult(content="No symbol found at the requested position", is_error=True)
        callers = [
            symbol
            for symbol in self._workspace_symbols(context.cwd)
            if symbol.outgoing_calls and symbol_name in symbol.outgoing_calls
        ][: parsed_input.max_results]
        if not callers:
            return ToolResult(content=f"No incoming calls found for {symbol_name}")
        lines = [f"Incoming calls for {symbol_name}:"]
        for symbol in callers:
            lines.append(
                f"- {symbol.name} @ {self._display_path(symbol.path, context.cwd)}:{symbol.line}:{symbol.character}"
            )
        return ToolResult(content="\n".join(lines))

    def _enclosing_symbol(self, parsed_input: LSPInput, context: ToolContext) -> SymbolInfo | None:
        path = self.resolve_path(context, parsed_input.file_path or "")
        symbols = self._symbols_for_file(path)
        best: SymbolInfo | None = None
        for symbol in symbols:
            if symbol.end_line is None:
                continue
            if self._position_in_symbol(parsed_input.line, parsed_input.character, symbol):
                if best is None or (best.end_line or 0) - best.line > (symbol.end_line or 0) - symbol.line:
                    best = symbol
        return best

    def _position_in_symbol(self, line: int, character: int, symbol: SymbolInfo) -> bool:
        if symbol.end_line is None:
            return False
        if line < symbol.line or line > symbol.end_line:
            return False
        if line == symbol.line and character < symbol.character:
            return False
        if symbol.end_character is not None and line == symbol.end_line and character > symbol.end_character:
            return False
        return True

    def _symbols_for_file(self, path: Path) -> list[SymbolInfo]:
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".py":
            return self._python_symbols(path, text)
        return self._generic_symbols(path, text)

    def _workspace_symbols(self, cwd: Path) -> list[SymbolInfo]:
        symbols: list[SymbolInfo] = []
        for path in self._workspace_files(cwd):
            try:
                symbols.extend(self._symbols_for_file(path))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
        return symbols

    def _workspace_files(self, cwd: Path) -> Iterable[Path]:
        for path in sorted(cwd.rglob("*")):
            if not path.is_file():
                continue
            if any(part in {".git", ".assist", "node_modules", "__pycache__"} for part in path.parts):
                continue
            if path.suffix in SUPPORTED_SYMBOL_EXTENSIONS:
                yield path

    def _find_symbol_definitions(self, symbol_name: str, cwd: Path) -> list[SymbolInfo]:
        return [symbol for symbol in self._workspace_symbols(cwd) if symbol.name == symbol_name]

    def _python_symbols(self, path: Path, text: str) -> list[SymbolInfo]:
        tree = ast.parse(text, filename=str(path))
        collector = _PythonSymbolCollector(path, text)
        collector.visit(tree)
        return collector.symbols

    def _generic_symbols(self, path: Path, text: str) -> list[SymbolInfo]:
        patterns = [
            (r"^\s*(?:export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)", "class"),
            (r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)", "function"),
            (r"^\s*(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\(", "function"),
            (r"^\s*interface\s+([A-Za-z_][A-Za-z0-9_]*)", "interface"),
            (r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", "type"),
            (r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)", "function"),
        ]
        compiled = [(re.compile(pattern), kind) for pattern, kind in patterns]
        symbols: list[SymbolInfo] = []
        for line_number, line_text in enumerate(text.splitlines(), start=1):
            for regex, kind in compiled:
                match = regex.search(line_text)
                if match:
                    column = (match.start(1) if match.lastindex else match.start()) + 1
                    symbols.append(
                        SymbolInfo(
                            name=match.group(1),
                            kind=kind,
                            path=path,
                            line=line_number,
                            character=column,
                        )
                    )
                    break
        return symbols

    def _token_at_position(self, text: str, line: int, character: int) -> str:
        target = self._line_at(text, line)
        if not target:
            return ""
        index = min(max(character - 1, 0), len(target))
        for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", target):
            if match.start() <= index <= match.end():
                return match.group(0)
        return ""

    def _line_at(self, text: str, line: int) -> str:
        lines = text.splitlines()
        if 1 <= line <= len(lines):
            return lines[line - 1].strip()
        return ""

    def _display_path(self, path: Path, cwd: Path) -> str:
        try:
            return str(path.relative_to(cwd))
        except ValueError:
            return str(path)


class _PythonSymbolCollector(ast.NodeVisitor):
    def __init__(self, path: Path, text: str) -> None:
        self.path = path
        self._lines = text.splitlines()
        self.symbols: list[SymbolInfo] = []
        self._containers: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.symbols.append(
            SymbolInfo(
                name=node.name,
                kind="class",
                path=self.path,
                line=node.lineno,
                character=self._name_character(node.lineno, node.col_offset, node.name),
                container=self._containers[-1] if self._containers else None,
                doc=(ast.get_docstring(node) or "").splitlines()[0] if ast.get_docstring(node) else "",
                end_line=getattr(node, "end_lineno", None),
                end_character=(getattr(node, "end_col_offset", None) or 0) + 1 if getattr(node, "end_col_offset", None) is not None else None,
            )
        )
        self._containers.append(node.name)
        self.generic_visit(node)
        self._containers.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._visit_function_like(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._visit_function_like(node)

    def _visit_function_like(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = "method" if self._containers else "function"
        outgoing_calls = tuple(sorted(_collect_outgoing_calls(node)))
        self.symbols.append(
            SymbolInfo(
                name=node.name,
                kind=kind,
                path=self.path,
                line=node.lineno,
                character=self._name_character(node.lineno, node.col_offset, node.name),
                container=self._containers[-1] if self._containers else None,
                doc=(ast.get_docstring(node) or "").splitlines()[0] if ast.get_docstring(node) else "",
                outgoing_calls=outgoing_calls,
                end_line=getattr(node, "end_lineno", None),
                end_character=(getattr(node, "end_col_offset", None) or 0) + 1 if getattr(node, "end_col_offset", None) is not None else None,
            )
        )
        self._containers.append(node.name)
        self.generic_visit(node)
        self._containers.pop()

    def _name_character(self, line_number: int, fallback_offset: int, name: str) -> int:
        if 1 <= line_number <= len(self._lines):
            line_text = self._lines[line_number - 1]
            index = line_text.find(name, fallback_offset)
            if index >= 0:
                return index + 1
        return fallback_offset + 1


def _collect_outgoing_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    calls: set[str] = set()

    class Collector(ast.NodeVisitor):
        def visit_Call(self, call_node: ast.Call) -> Any:
            func = call_node.func
            if isinstance(func, ast.Name):
                calls.add(func.id)
            elif isinstance(func, ast.Attribute):
                calls.add(func.attr)
            self.generic_visit(call_node)

        def visit_FunctionDef(self, inner: ast.FunctionDef) -> Any:
            return None

        def visit_AsyncFunctionDef(self, inner: ast.AsyncFunctionDef) -> Any:
            return None

        def visit_ClassDef(self, inner: ast.ClassDef) -> Any:
            return None

    collector = Collector()
    for child in node.body:
        collector.visit(child)
    return calls
