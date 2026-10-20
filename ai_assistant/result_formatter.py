"""Presentation-only formatting helpers for AI result text."""

import re
from html import escape


CANONICAL_SECTIONS = [
    "Chosen Analysis Method",
    "Known Values and Reference Node",
    "Circuit Constraints",
    "KCL/KVL Equations",
    "Solve the Equations",
    "Requested Quantity",
    "Verification",
    "Final Interpretation",
]

_ALIASES = {
    "analysis method": "Chosen Analysis Method",
    "chosen method": "Chosen Analysis Method",
    "selected analysis method": "Chosen Analysis Method",
    "known values": "Known Values and Reference Node",
    "known data and reference node": "Known Values and Reference Node",
    "reference node and known values": "Known Values and Reference Node",
    "equations": "KCL/KVL Equations",
    "nodal equations": "KCL/KVL Equations",
    "kcl equations": "KCL/KVL Equations",
    "kvl equations": "KCL/KVL Equations",
    "solving": "Solve the Equations",
    "equation solution": "Solve the Equations",
    "solving the system": "Solve the Equations",
    "requested value": "Requested Quantity",
    "requested quantities": "Requested Quantity",
    "target quantity": "Requested Quantity",
    "power check": "Verification",
    "validation": "Verification",
    "verification and power balance": "Verification",
}

_FINAL_HEADINGS = {"final answer", "final answers", "conclusion"}
_HEADING_MARKERS_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_BOLD_RE = re.compile(r"^\s*\*{1,3}(.+?)\*{1,3}\s*$")
_STEP_PREFIX_RE = re.compile(r"^\s*(?:step\s*)?\d+\s*[\.)]\s*", re.IGNORECASE)
_VARIABLE_RE = re.compile(r"\b([VIP])([A-Z]|R\d+|V\d+)\b")
_PROSE_START_RE = re.compile(
    r"^(using|since|because|then|now|therefore|thus|the|this|that|we|to|under|rounding)\b",
    re.IGNORECASE,
)


def normalize_heading(text: str) -> str:
    """Remove provider numbering/Markdown decorations from one heading line."""
    heading = (text or "").strip()
    heading = _HEADING_MARKERS_RE.sub("", heading).strip()
    bold_match = _BOLD_RE.match(heading)
    if bold_match:
        heading = bold_match.group(1).strip()
    heading = _STEP_PREFIX_RE.sub("", heading).strip()
    heading = heading.strip("*_` ")
    heading = heading[:-1].strip() if heading.endswith(":") else heading
    return re.sub(r"\s+", " ", heading).strip()


def canonicalize_heading(text: str) -> str | None:
    """Return canonical major section title, if text names one."""
    heading = normalize_heading(text)
    key = heading.casefold()
    for canonical in CANONICAL_SECTIONS:
        if key == canonical.casefold():
            return canonical
    return _ALIASES.get(key)


def is_final_answer_heading(text: str) -> bool:
    """Return whether text denotes a final-answer section heading."""
    return normalize_heading(text).casefold() in _FINAL_HEADINGS


def escape_text(text: str) -> str:
    """HTML-escape untrusted AI text without escaping quote characters."""
    return escape(text or "", quote=False)


def format_variable_tokens(text: str) -> str:
    """Render underscore-number variable suffixes as HTML subscripts."""
    def replace(match):
        """Convert one variable-token regex match to escaped HTML."""
        base, subscript = match.groups()
        return f"{base}<sub>{escape_text(subscript)}</sub>"

    return _VARIABLE_RE.sub(replace, text)


def normalize_equation_operators(text: str) -> str:
    """Replace common plain-text equation operators with display symbols."""
    equation = text or ""
    equation = equation.replace("<=", "≤").replace(">=", "≥").replace("!=", "≠")
    equation = re.sub(r"\s*->\s*", " → ", equation)
    equation = re.sub(r"(?<=\S)\s*\*\s*(?=\S)", " × ", equation)
    equation = re.sub(r"(?<=\s)-(?=\s|\d|[A-Z(])", "−", equation)
    equation = re.sub(r"(?<=\d)\s*-\s*(?=\d)", " − ", equation)
    equation = re.sub(r"\s*/\s*", " / ", equation)
    equation = re.sub(r"\s+", " ", equation)
    return equation.strip()


def looks_like_equation(line: str) -> bool:
    """Heuristically identify equation lines without treating prose as math."""
    stripped = (line or "").strip()
    if not stripped or len(stripped) > 500:
        return False
    if _PROSE_START_RE.match(stripped):
        return False
    if stripped.endswith((".", ":", ";")):
        return False
    if re.search(r"\b[a-z]{4,}\b", stripped):
        return False
    operators = len(re.findall(r"(=|\+|-|\*|×|/|\^|≈|≤|≥|≠)", stripped))
    has_variable = bool(re.search(r"\b(?:V[A-F]|I(?:R\d+|V\d+|\d+)|P(?:R\d+|V\d+|sum)|R\d+)\b", stripped))
    return "=" in stripped and operators >= 1 and (has_variable or operators >= 3)


def render_equation(line: str) -> str:
    """Render one normalized equation inside a styled HTML block."""
    equation = normalize_equation_operators(line)
    equation = format_variable_tokens(escape_text(equation))
    return f'<div class="equation-block">{equation}</div>'


def render_heading(title: str, step_number: int | None = None) -> str:
    """Render a canonical explanation heading with an optional step number."""
    safe_title = escape_text(title)
    if step_number is None:
        return f'<h3 class="solution-subheading">{safe_title}</h3>'
    return f'<h2 class="solution-step">Step {step_number}. {safe_title}</h2>'


def _is_heading_candidate(raw_line):
    """Return whether a Markdown line should be parsed as a major heading."""
    stripped = raw_line.strip()
    if not stripped:
        return False
    if canonicalize_heading(stripped) or is_final_answer_heading(stripped):
        return True
    if _HEADING_MARKERS_RE.match(stripped):
        return True
    return False


def format_explanation_sections(text: str) -> str:
    """Convert major explanation headings to renderer-numbered HTML headings."""
    if not text:
        return ""

    formatted_lines = []
    seen = set()
    in_code_fence = False

    for raw_line in str(text).splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            formatted_lines.append(raw_line)
            continue
        if in_code_fence:
            formatted_lines.append(raw_line)
            continue

        canonical = canonicalize_heading(stripped)
        if canonical:
            step_number = CANONICAL_SECTIONS.index(canonical) + 1
            seen.add(canonical)
            formatted_lines.append(render_heading(canonical, step_number))
            continue

        if is_final_answer_heading(stripped):
            formatted_lines.append(render_heading(normalize_heading(stripped)))
            continue

        if _is_heading_candidate(stripped):
            formatted_lines.append(render_heading(normalize_heading(stripped)))
            continue

        if looks_like_equation(stripped):
            formatted_lines.append(render_equation(stripped))
            continue

        formatted_lines.append(raw_line)

    return "\n".join(formatted_lines)
