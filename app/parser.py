"""AST parser for the Codebase Health Agent.

Walks tree-sitter trees to produce structural metrics. Downstream agents
(Security, Clean Code, Performance) consume this instead of dumping whole
files into an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from tree_sitter import Node, Parser, Tree
from tree_sitter_language_pack import detect_language_from_path, get_language

# Node types that appear across Python / JS / TS / Go / Java / Rust.
FUNCTION_TYPES = frozenset(
    {
        "function_definition",
        "function_declaration",
        "function_item",
        "method_definition",
        "method_declaration",
        "arrow_function",
        "func_literal",
        "lambda",
        "lambda_expression",
    }
)
CLASS_TYPES = frozenset(
    {
        "class_definition",
        "class_declaration",
        "class_specifier",
        "struct_item",
        "impl_item",
        "interface_declaration",
        "enum_declaration",
        "type_declaration",
    }
)
IMPORT_TYPES = frozenset(
    {
        "import_statement",
        "import_from_statement",
        "import_declaration",
        "import_spec",
        "use_declaration",
        "preproc_include",
    }
)
CALL_TYPES = frozenset(
    {
        "call",
        "call_expression",
        "method_invocation",
        "function_call_expression",
    }
)
DECISION_TYPES = frozenset(
    {
        "if_statement",
        "elif_clause",
        "else_clause",
        "for_statement",
        "for_in_statement",
        "for_range_loop",
        "while_statement",
        "do_statement",
        "match_statement",
        "switch_statement",
        "case_clause",
        "catch_clause",
        "except_clause",
        "conditional_expression",
        "ternary_expression",
        "boolean_operator",
        "binary_expression",
        "try_statement",
        "with_statement",
    }
)
LOOP_TYPES = frozenset(
    {
        "for_statement",
        "for_in_statement",
        "for_range_loop",
        "while_statement",
        "do_statement",
    }
)
#kodun sağa doğru ne kadar uzadığını derin yapısını göstermek için kullanılır
NESTING_TYPES = FUNCTION_TYPES | CLASS_TYPES | DECISION_TYPES | LOOP_TYPES

# bu kodun güvenli olup olmadığını kontrol eder
RISKY_CALL_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "loads",
        "load",
        "dumps",
        "system",
        "popen",
        "call",
        "run",
        "Popen",
        "getattr",
        "setattr",
        "globals",
        "locals",
        "innerHTML",
        "document.write",
        "Function",
        "setTimeout",
        "setInterval",
    }
)


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    start_byte: int
    end_byte: int


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    kind: str
    span: SourceSpan
    line_count: int
    complexity: int
    nesting: int
    parameter_count: int = 0


@dataclass(frozen=True, slots=True)
class CallSite:
    name: str
    span: SourceSpan
    risky: bool


@dataclass(frozen=True, slots=True)
class FileFacts:
    """tek bir kaynak dosyasından çıkarılan kesin mimari özet.
    ajanlar ham kod metni yerine doğrudan bu veriyi okur."""

    path: str    
    language: str
    loc: int    #toplam satır sayısı
    node_count: int  # AST ağacındaki toplam düğüm sayısı
    max_depth: int
    parse_error_count: int
    functions: list[Symbol] = field(default_factory=list) #fonksiyonların listesi
    classes: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)
    loop_count: int = 0
    decision_count: int = 0

    @property
    def avg_function_complexity(self) -> float:
        if not self.functions:
            return 0.0
        return sum(fn.complexity for fn in self.functions) / len(self.functions)

    @property
    def longest_function_lines(self) -> int:
        if not self.functions:
            return 0
        return max(fn.line_count for fn in self.functions)


class UnsupportedLanguageError(ValueError):
    pass


class ParseError(RuntimeError):
    pass


@lru_cache(maxsize=32)
def _parser_for(language: str) -> Parser:
    return Parser(get_language(language))


def detect_language(path: str | Path) -> str:
    language = detect_language_from_path(str(path))
    if not language:
        raise UnsupportedLanguageError(f"Cannot detect language for {path}")
    return language


def parse_file(path: str | Path, *, language: str | None = None) -> FileFacts:
    file_path = Path(path)
    source = file_path.read_bytes()
    return parse_source(
        source,
        path=str(file_path),
        language=language or detect_language(file_path),
    )


def parse_source(
    source: bytes | str,
    *,
    path: str = "<memory>",
    language: str,
) -> FileFacts:
    """Kodu Tree-Sitter ile AST düğümlerine ayırır.'while' döngüsü ile ağacın kökünden başlayarak tüm dalları (Tree Traversal) gezer"""
    if isinstance(source, str):
        source = source.encode("utf-8")

    try:
        tree = _parser_for(language).parse(source)
    except Exception as exc:  # grammar download / ABI issues surface here
        raise ParseError(f"Failed to parse {path} as {language}") from exc

    root = tree.root_node
    functions: list[Symbol] = []
    classes: list[Symbol] = []
    imports: list[str] = []
    calls: list[CallSite] = []
    loop_count = 0
    decision_count = 0
    node_count = 0
    max_depth = 0
    error_count = 0

    cursor = root.walk()
    depth = 0
    reached_root = False
    while not reached_root:
        node = cursor.node
        if node is not None:
            node_count += 1
            max_depth = max(max_depth, depth)
            if node.is_error or node.is_missing:
                error_count += 1

            kind = node.type
            if kind in FUNCTION_TYPES:
                functions.append(_symbol_from_node(node, kind="function", depth=depth))
            elif kind in CLASS_TYPES:
                classes.append(_symbol_from_node(node, kind="class", depth=depth))
            elif kind in IMPORT_TYPES:
                text = _node_text(node)
                if text:
                    imports.append(" ".join(text.split()))
            elif kind in CALL_TYPES:
                name = _call_name(node)
                if name:
                    calls.append(
                        CallSite(
                            name=name,
                            span=_span(node),
                            risky=_is_risky_call(name),
                        )
                    )
            if kind in LOOP_TYPES:
                loop_count += 1
            if kind in DECISION_TYPES:
                decision_count += 1

        if cursor.goto_first_child():
            depth += 1
            continue
        if cursor.goto_next_sibling():
            continue
        while True:
            if not cursor.goto_parent():
                reached_root = True
                break
            depth -= 1
            if cursor.goto_next_sibling():
                break

    return FileFacts(
        path=path,
        language=language,
        loc=_line_count(source),
        node_count=node_count,
        max_depth=max_depth,
        parse_error_count=error_count,
        functions=functions,
        classes=classes,
        imports=imports,
        calls=calls,
        loop_count=loop_count,
        decision_count=decision_count,
    )


def parse_tree(path: str | Path, *, language: str | None = None) -> Tree:
    """Return the raw tree-sitter Tree when an agent needs custom queries."""
    file_path = Path(path)
    source = file_path.read_bytes()
    lang = language or detect_language(file_path)
    return _parser_for(lang).parse(source)


def _symbol_from_node(node: Node, *, kind: str, depth: int) -> Symbol:
    name = _declared_name(node)
    body = node.child_by_field_name("body") or node
    return Symbol(
        name=name,
        kind=kind,
        span=_span(node),
        line_count=max(1, node.end_point[0] - node.start_point[0] + 1),
        complexity=_cyclomatic(body),
        nesting=depth,
        parameter_count=_parameter_count(node),
    )


def _cyclomatic(node: Node) -> int:
    """McCabe-style approximation: 1 + decision points inside the node.
    bu kodun karmaşıklığını hesaplar. skor yükseldikçe clean code ihlali artar.
    """
    score = 1
    cursor = node.walk()
    reached_root = False
    while not reached_root:
        current = cursor.node
        if current is not None and current.id != node.id:
            kind = current.type
            if kind in DECISION_TYPES:
                if kind == "binary_expression":
                    operator = _binary_operator(current)
                    if operator in {"&&", "||", "and", "or"}:
                        score += 1
                else:
                    score += 1
        if cursor.goto_first_child():
            continue
        if cursor.goto_next_sibling():
            continue
        while True:
            if not cursor.goto_parent() or cursor.node == node:
                reached_root = True
                break
            if cursor.goto_next_sibling():
                break
    return score


def _declared_name(node: Node) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(name_node) or "<anonymous>"
    for child in node.named_children:
        if child.type in {"identifier", "property_identifier", "type_identifier"}:
            return _node_text(child) or "<anonymous>"
    return "<anonymous>"


def _parameter_count(node: Node) -> int:
    params = (
        node.child_by_field_name("parameters")
        or node.child_by_field_name("parameter_list")
        or node.child_by_field_name("formal_parameters")
    )
    if params is None:
        return 0
    return sum(1 for child in params.named_children if child.type != "comment")


def _call_name(node: Node) -> str:
    function = node.child_by_field_name("function") or node.named_child(0)
    if function is None:
        return ""
    text = _node_text(function) or ""
    if "." in text:
        return text.rsplit(".", 1)[-1]
    return text


def _is_risky_call(name: str) -> bool:
    leaf = name.rsplit(".", 1)[-1]
    return leaf in RISKY_CALL_NAMES


def _binary_operator(node: Node) -> str:
    for child in node.children:
        if not child.is_named:
            return _node_text(child) or ""
    return ""


def _span(node: Node) -> SourceSpan:
    start_line, start_col = node.start_point
    end_line, end_col = node.end_point
    return SourceSpan(
        start_line=start_line + 1,
        start_col=start_col,
        end_line=end_line + 1,
        end_col=end_col,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
    )


def _node_text(node: Node) -> str:
    raw = node.text
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _line_count(source: bytes) -> int:
    if not source:
        return 0
    return source.count(b"\n") + (0 if source.endswith(b"\n") else 1)
