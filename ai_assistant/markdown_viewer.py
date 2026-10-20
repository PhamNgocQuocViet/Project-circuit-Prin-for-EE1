"""
MarkdownViewer: renders AI Markdown and LaTeX output for result dialogs.

The preferred renderer is QWebEngineView with locally bundled KaTeX-compatible
assets. If PyQtWebEngine is not installed, the widget falls back to QTextBrowser
with readable math conversion so the application still opens.
"""

import re
from html import escape

from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtWidgets import QApplication, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget

from app_paths import resource_path
from ai_assistant.result_formatter import format_explanation_sections

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover - depends on optional runtime package
    QWebEngineView = None

try:
    import markdown as _markdown
except ImportError:  # pragma: no cover - guarded so the UI never crashes
    _markdown = None


_BLOCK_MATH_PATTERNS = (
    re.compile(r"\$\$(.+?)\$\$", re.DOTALL),
    re.compile(r"\\\[(.+?)\\\]", re.DOTALL),
)
_INLINE_MATH_PATTERNS = (
    re.compile(r"\\\((.+?)\\\)", re.DOTALL),
    re.compile(r"(?<!\$)\$(?!\$)([^\n$]+?)\$(?!\$)"),
)
_RESPONSE_TAG_RE = re.compile(r"</?\s*(?:SOLUTION|EXPLAI?NATION)\s*>", re.IGNORECASE)
_INTERNAL_HTML_RE = re.compile(
    r"<(?:h2|h3|div)\s+class=\"(?:solution-step|solution-subheading|equation-block)\".*?</(?:h2|h3|div)>",
    re.DOTALL,
)

_GREEK_MAP = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "theta": "θ", "lambda": "λ", "mu": "μ",
    "pi": "π", "sigma": "σ", "phi": "φ", "omega": "ω",
    "Omega": "Ω", "Delta": "Δ", "Sigma": "Σ",
}

_SYMBOL_MAP = {
    r"\sum": "∑",
    r"\times": "×",
    r"\cdot": "·",
    r"\pm": "±",
    r"\mp": "∓",
    r"\leq": "≤",
    r"\geq": "≥",
    r"\neq": "≠",
    r"\approx": "≈",
    r"\infty": "∞",
    r"\rightarrow": "→",
    r"\to": "→",
    r"\left": "",
    r"\right": "",
    r"\,": " ",
    r"\;": " ",
    r"\!": "",
}

_FRAC_RE = re.compile(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT_RE = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
_TAG_RE = re.compile(r"\\tag\s*\{([^{}]+)\}")
_SUP_RE = re.compile(r"\^\{([^{}]+)\}|\^(\w)")
_SUB_RE = re.compile(r"_\{([^{}]+)\}|_(\w)")
_GREEK_RE = re.compile(r"\\(" + "|".join(sorted(_GREEK_MAP, key=len, reverse=True)) + r")\b")
_TEXT_RE = re.compile(r"\\text\{([^{}]*)\}")
_MATHRM_RE = re.compile(r"\\mathrm\{([^{}]+)\}")
_BARE_TAG_RE = re.compile(r"\\tag\s*(\d+)\b")
_PAREN_FRACTION_RE = re.compile(
    r"\(((?:[^()\n]|\([^()\n]*\))+)\)\s*/\s*(?:\(((?:[^()\n]|\([^()\n]*\))+)\)|([^+\-*/=\n]+))"
)
_SIMPLE_FRACTION_RE = re.compile(
    r"(?<![\\\w}])([A-Za-z][A-Za-z0-9]*|-?\d+(?:\.\d+)?)\s*/\s*(\(?[A-Za-z0-9.]+\)?)"
)
_INLINE_UNIT_EXPR_RE = re.compile(
    r"(?<!\\\()"
    r"(?P<expr>\b[A-Za-z](?:_\{?[A-Za-z0-9]+\}?|[A-Za-z0-9]*)"
    r"\s*=\s*[-+]?\s*(?:[0-9.]+|[A-Za-z](?:_\{?[A-Za-z0-9]+\}?|[A-Za-z0-9]*))"
    r"(?:\\,\s*)?\s*\\mathrm\{(?:V|A|mA|W|mW)\})"
)
_MALFORMED_MATHRM_UNITS = (
    (re.compile(r"\\mathrm\s*mA\b"), r"\\mathrm{mA}"),
    (re.compile(r"\\mathrm\s*mW\b"), r"\\mathrm{mW}"),
    (re.compile(r"\\mathrm\s*e-6\b"), r"10^{-6}"),
    (re.compile(r"\\mathrm\s*V\b"), r"\\mathrm{V}"),
    (re.compile(r"\\mathrm\s*A\b"), r"\\mathrm{A}"),
    (re.compile(r"\\mathrm\s*W\b"), r"\\mathrm{W}"),
)


def normalize_latex_input(text):
    """Normalize only simple malformed unit commands before rendering."""
    if not text:
        return ""
    text = (
        text.replace("\\\\[", "\\[")
        .replace("\\\\]", "\\]")
        .replace("\\\\(", "\\(")
        .replace("\\\\)", "\\)")
    )
    for pattern, replacement in _MALFORMED_MATHRM_UNITS:
        text = pattern.sub(replacement, text)
    text = _BARE_TAG_RE.sub(r"\\tag{\1}", text)
    return text


def _has_math_delimiters(text):
    """Return whether text already contains supported LaTeX delimiters."""
    return any(token in text for token in ("\\(", "\\)", "\\[", "\\]", "$"))


def _looks_like_standalone_equation(line):
    """Detect an unwrapped equation occupying an entire source line."""
    if not line or _has_math_delimiters(line):
        return False
    if line.startswith(("#", "-", "*", "+")) or re.match(r"^\d+[.)]\s+", line):
        return False
    if ":" in line:
        return False
    if re.search(r"\b[A-Za-z]{4,}\b", line):
        return False
    has_equation_operator = "=" in line or "\\tag{" in line
    has_math_syntax = any(token in line for token in ("\\", "_", "^", "/", "×"))
    return has_equation_operator and has_math_syntax


def _wrap_inline_unit_expressions(line):
    """Wrap loose numeric unit expressions for consistent math rendering."""
    if _has_math_delimiters(line):
        return line
    return _INLINE_UNIT_EXPR_RE.sub(r"\\(\g<expr>\\)", line)


def _wrap_loose_latex(text):
    """Wrap obvious delimiter-free math emitted by the AI, without broad repair."""
    wrapped_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if _looks_like_standalone_equation(stripped):
            indent = line[: len(line) - len(line.lstrip())]
            wrapped_lines.append(f"{indent}\\[{stripped}\\]")
        else:
            wrapped_lines.append(_wrap_inline_unit_expressions(line))
    return "\n".join(wrapped_lines)


def _normalize_math_expression(expression):
    """Improve common AI-emitted electrical equations before KaTeX renders them."""
    expression = expression.strip()
    expression = expression.replace("Ω", r"\Omega")

    previous = None
    while previous != expression:
        previous = expression

        def replace_fraction(match):
            """Rewrite one parenthesized fraction into canonical LaTeX."""
            numerator = match.group(1).strip()
            denominator = (match.group(2) or match.group(3)).strip()
            return rf"\frac{{{numerator}}}{{{denominator}}}"

        expression = _PAREN_FRACTION_RE.sub(replace_fraction, expression)

    expression = _SIMPLE_FRACTION_RE.sub(
        lambda match: rf"\frac{{{match.group(1).strip()}}}{{{match.group(2).strip('() ')}}}",
        expression,
    )
    return expression


def _extract_math_tokens(text, normalize_expressions=True):
    """Replace math delimiters with placeholders so Markdown parsing is safe."""
    tokens = {}
    counter = 0

    def store(kind, expression):
        """Replace a math expression with a stable internal placeholder."""
        nonlocal counter
        counter += 1
        key = f"@@MATH{counter}@@"
        if normalize_expressions:
            expression = _normalize_math_expression(expression)
        tokens[key] = (kind, expression.strip())
        return key

    for pattern in _BLOCK_MATH_PATTERNS:
        text = pattern.sub(lambda match: store("display", match.group(1)), text)
    for pattern in _INLINE_MATH_PATTERNS:
        text = pattern.sub(lambda match: store("inline", match.group(1)), text)
    return text, tokens


def _extract_internal_html_tokens(text):
    """Protect renderer-generated HTML fragments during Markdown escaping."""
    tokens = {}
    counter = 0

    def store(match):
        """Store one trusted internal HTML fragment and return its token."""
        nonlocal counter
        counter += 1
        key = f"@@HTML{counter}@@"
        tokens[key] = match.group(0)
        return f"\n\n{key}\n\n"

    return _INTERNAL_HTML_RE.sub(store, text), tokens


def _restore_internal_html_tokens(html, tokens):
    """Restore previously protected internal HTML placeholders."""
    for key, value in tokens.items():
        html = html.replace(key, value)
    html = re.sub(r"<p>\s*(<h[23] class=\"solution-[^\"]+\">.*?</h[23]>)\s*</p>", r"\1", html, flags=re.DOTALL)
    html = re.sub(r"<p>\s*(<div class=\"equation-block\">.*?</div>)\s*</p>", r"\1", html, flags=re.DOTALL)
    html = re.sub(r"<p>\s*(<h[23] class=\"solution-[^\"]+\">.*?</h[23]>)\s*<br\s*/?>\s*</p>", r"\1", html, flags=re.DOTALL)
    return html


def _restore_math_tokens_for_web(html, tokens):
    """Restore math placeholders as delimiters consumed by browser KaTeX."""
    for key, (kind, expression) in tokens.items():
        escaped_expression = escape(expression)
        if kind == "display":
            replacement = f'<span class="math-display" data-display="true">{escaped_expression}</span>'
        else:
            replacement = f'<span class="math-inline" data-display="false">{escaped_expression}</span>'
        html = html.replace(key, replacement)
    html = re.sub(r"<p>\s*(<span class=\"math-display\".*?</span>)\s*</p>", r"\1", html, flags=re.DOTALL)
    return html


def _latex_to_readable(expr, display=False):
    """Best-effort conversion used only by the QTextBrowser fallback."""
    expr = expr.strip()

    def fraction_html(match):
        """Render a simple fraction with readable fallback HTML."""
        numerator = _latex_to_readable(match.group(1), display=display)
        denominator = _latex_to_readable(match.group(2), display=display)
        if display:
            return f"({numerator}) / ({denominator})"
        return (
            '<span class="eq-frac-inline">'
            f"<sup>{numerator}</sup>"
            "&#8260;"
            f"<sub>{denominator}</sub>"
            "</span>"
        )

    previous = None
    while previous != expr:
        previous = expr
        expr = _FRAC_RE.sub(fraction_html, expr)

    expr = _SQRT_RE.sub(lambda match: f"√({match.group(1)})", expr)
    expr = _TEXT_RE.sub(lambda match: match.group(1), expr)
    expr = _MATHRM_RE.sub(lambda match: match.group(1), expr)
    expr = _TAG_RE.sub(lambda match: f"({match.group(1)})", expr)
    expr = _GREEK_RE.sub(lambda match: _GREEK_MAP[match.group(1)], expr)
    for latex_symbol, replacement in _SYMBOL_MAP.items():
        expr = expr.replace(latex_symbol, replacement)
    expr = _SUP_RE.sub(lambda match: f"<sup>{match.group(1) or match.group(2)}</sup>", expr)
    expr = _SUB_RE.sub(lambda match: f"<sub>{match.group(1) or match.group(2)}</sub>", expr)
    return expr.replace("{", "").replace("}", "").strip()


def _restore_math_tokens_for_text_browser(html, tokens):
    """Restore math placeholders using the QTextBrowser-safe fallback."""
    for key, (kind, expression) in tokens.items():
        readable = _latex_to_readable(expression, display=(kind == "display"))
        if kind == "display":
            replacement = f'<div class="math-display-fallback">{readable}</div>'
        else:
            replacement = f'<span class="math-inline-fallback">{readable}</span>'
        html = html.replace(key, replacement)
    html = re.sub(r"<p>\s*(<div class=\"math-display-fallback\">.*?</div>)\s*</p>", r"\1", html, flags=re.DOTALL)
    return html


def _render_inline_markdown(text):
    """Render supported inline Markdown after protecting math content."""
    text = escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"<em>\1</em>", text)
    return text


def _fallback_markdown_to_html(text):
    """Convert a conservative Markdown subset without external packages."""
    lines = text.splitlines()
    html_parts = []
    list_type = None
    paragraph_lines = []

    def close_paragraph():
        """Flush pending paragraph lines into the output buffer."""
        if paragraph_lines:
            html_parts.append("<p>" + "<br>".join(paragraph_lines) + "</p>")
            paragraph_lines.clear()

    def close_list():
        """Close the active list element when one is open."""
        nonlocal list_type
        if list_type is not None:
            html_parts.append(f"</{list_type}>")
            list_type = None

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            close_paragraph()
            close_list()
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        bullet_match = re.match(r"^[-*+]\s+(.+)$", stripped)
        numbered_match = re.match(r"^\d+[.)]\s+(.+)$", stripped)

        if heading_match:
            close_paragraph()
            close_list()
            level = min(len(heading_match.group(1)), 4)
            html_parts.append(f"<h{level}>{_render_inline_markdown(heading_match.group(2))}</h{level}>")
        elif bullet_match:
            close_paragraph()
            if list_type != "ul":
                close_list()
                html_parts.append("<ul>")
                list_type = "ul"
            html_parts.append(f"<li>{_render_inline_markdown(bullet_match.group(1))}</li>")
        elif numbered_match:
            close_paragraph()
            if list_type != "ol":
                close_list()
                html_parts.append("<ol>")
                list_type = "ol"
            html_parts.append(f"<li>{_render_inline_markdown(numbered_match.group(1))}</li>")
        else:
            close_list()
            paragraph_lines.append(_render_inline_markdown(stripped))

    close_paragraph()
    close_list()
    return "\n".join(html_parts)


def render_markdown_to_html(text, web_math=True):
    """Convert Markdown to HTML while preserving/restoring math delimiters."""
    if not text:
        return ""

    try:
        text = _RESPONSE_TAG_RE.sub("", str(text))
        text = format_explanation_sections(text)
        text = _wrap_loose_latex(normalize_latex_input(text))
        protected_text, html_tokens = _extract_internal_html_tokens(text)
        protected_text, math_tokens = _extract_math_tokens(protected_text, normalize_expressions=web_math)
        if _markdown is not None:
            html_body = _markdown.markdown(
                protected_text,
                extensions=["extra", "sane_lists", "nl2br", "tables", "fenced_code"],
            )
        else:
            html_body = _fallback_markdown_to_html(protected_text)

        if web_math:
            html_body = _restore_math_tokens_for_web(html_body, math_tokens)
        else:
            html_body = _restore_math_tokens_for_text_browser(html_body, math_tokens)
        return _restore_internal_html_tokens(html_body, html_tokens)
    except Exception:  # noqa: BLE001 - renderer must never crash result dialog
        return "<pre>" + escape(str(text)) + "</pre>"


def _viewer_theme_name():
    """Return the concrete theme currently stored on QApplication."""
    app = QApplication.instance()
    if app is None:
        return "light"
    return str(app.property("resolvedTheme") or "light").lower()


def _read_text_resource(*parts):
    """Read a bundled UTF-8 viewer asset, returning an empty string on failure."""
    path = resource_path(*parts)
    try:
        with open(path, "r", encoding="utf-8") as resource_file:
            return resource_file.read()
    except OSError:
        return ""


def _document_css(theme_name):
    """Build the complete viewer stylesheet for a concrete theme."""
    if theme_name == "dark":
        background = "#20262D"
        text = "#F1F5F9"
        secondary = "#B8C2CC"
        equation_background = "#171C22"
        equation_block_background = "transparent"
        divider = "#3B4652"
        code_background = "#171C22"
        link = "#8EC5FF"
        equation_accent = "#4F8CC9"
    else:
        background = "#FFFFFF"
        text = "#202124"
        secondary = "#5F6F80"
        equation_background = "#F5F7FA"
        equation_block_background = "transparent"
        divider = "#D8DDE3"
        code_background = "#F5F7FA"
        link = "#1F6FB2"
        equation_accent = "#3B73A8"

    katex_css = _read_text_resource("ui", "vendor", "katex", "katex.min.css")
    return f"""
        {katex_css}
        .katex {{
            font-size: 1em;
            line-height: 1.65;
            white-space: normal;
        }}
        .katex-frac {{
            display: inline-flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            vertical-align: middle;
            margin: 0 0.18em;
            line-height: 1.15;
            font-size: 1em;
        }}
        .katex-frac-num {{
            display: block;
            padding: 0 0.22em 0.12em 0.22em;
        }}
        .katex-frac-den {{
            display: block;
            border-top: 1px solid currentColor;
            padding: 0.12em 0.22em 0 0.22em;
        }}
        html, body {{
            min-height: 100%;
            margin: 0;
            background: {background};
            color: {text};
            font-family: "Segoe UI", Arial, sans-serif;
            font-size: 10.5pt;
            line-height: 1.5;
            overflow-wrap: anywhere;
            word-break: break-word;
        }}
        body {{
            padding: 18px 22px;
        }}
        h1, h2, h3, h4 {{
            color: {text};
            margin: 14px 0 8px 0;
            font-weight: 700;
        }}
        .solution-step {{
            margin: 22px 0 10px 0;
            padding-bottom: 5px;
            border-bottom: 1px solid {divider};
            color: {text};
            font-size: 1.15em;
            font-weight: 600;
        }}
        .solution-subheading {{
            margin: 18px 0 8px 0;
            color: {text};
            font-size: 1.05em;
            font-weight: 600;
        }}
        p {{
            margin: 0 0 10px 0;
            overflow-wrap: anywhere;
        }}
        ul, ol {{
            margin-top: 4px;
            margin-bottom: 12px;
            padding-left: 26px;
        }}
        li {{
            margin-bottom: 4px;
        }}
        table {{
            border-collapse: collapse;
            margin: 10px 0 14px 0;
            width: 100%;
        }}
        th, td {{
            border: 1px solid {divider};
            padding: 6px 8px;
            text-align: left;
        }}
        th {{
            color: {text};
            background: {equation_background};
        }}
        strong {{
            color: {text};
            font-weight: 700;
        }}
        em {{
            color: {secondary};
        }}
        code, pre {{
            color: {text};
            background: {code_background};
            border: 1px solid {divider};
            border-radius: 5px;
        }}
        code {{
            padding: 1px 4px;
        }}
        pre {{
            padding: 10px;
            overflow-x: auto;
            white-space: pre;
        }}
        hr {{
            border: none;
            border-top: 1px solid {divider};
            margin: 14px 0;
        }}
        a {{
            color: {link};
        }}
        .math-display, .katex-display {{
            display: block;
            box-sizing: border-box;
            margin: 16px 0 18px 0;
            padding: 12px 14px;
            max-width: 100%;
            overflow-x: auto;
            overflow-y: visible;
            overflow-wrap: normal;
            white-space: nowrap;
            text-align: left;
            line-height: 1.75;
            background: {equation_background};
            border: 1px solid {divider};
            border-radius: 6px;
        }}
        .equation-block {{
            box-sizing: border-box;
            margin: 12px 0;
            padding: 6px 10px;
            max-width: 100%;
            overflow-x: auto;
            overflow-wrap: anywhere;
            white-space: pre-wrap;
            text-align: left;
            font-family: "Segoe UI", Arial, sans-serif;
            font-size: 1.03em;
            line-height: 1.5;
            background: {equation_block_background};
            border-left: 3px solid {equation_accent};
            border-radius: 4px;
        }}
        .math-inline, .katex-inline {{
            display: inline;
        }}
        .math-display-fallback {{
            box-sizing: border-box;
            margin: 16px 0 18px 0;
            padding: 12px 14px;
            max-width: 100%;
            overflow-x: auto;
            overflow-y: visible;
            overflow-wrap: normal;
            white-space: pre-wrap;
            text-align: left;
            line-height: 1.75;
            background: {equation_background};
            border: 1px solid {divider};
            border-radius: 6px;
        }}
        .math-display-fallback, .math-display-fallback * {{
            font-family: "Segoe UI", Arial, sans-serif;
        }}
        .eq-frac-inline {{
            white-space: nowrap;
            margin: 0 2px;
        }}
        .eq-frac-inline sup,
        .eq-frac-inline sub {{
            font-size: 0.78em;
            line-height: 0;
        }}
        .eq-frac {{
            display: inline-table;
            vertical-align: middle;
            margin: 0 3px;
            line-height: 1.05;
            font-size: 1.05em;
            text-align: center;
        }}
        .eq-num {{
            display: table-row;
            padding: 0 4px 2px 4px;
            border-bottom: 1px solid currentColor;
            white-space: nowrap;
        }}
        .eq-den {{
            display: table-row;
            padding: 2px 4px 0 4px;
            white-space: nowrap;
        }}
        .math-inline-fallback {{
            background: {equation_background};
            border: 1px solid {divider};
            border-radius: 4px;
            padding: 1px 4px;
        }}
    """


def build_markdown_document(html_body, theme_name=None, include_scripts=True):
    """Wrap rendered body HTML in the themed standalone viewer document.

    Args:
        html_body: Already rendered and escaped response body.
        theme_name: Optional concrete light/dark theme override.
        include_scripts: Whether to include bundled browser math scripts.
    """
    theme_name = theme_name or _viewer_theme_name()
    scripts = ""
    if include_scripts:
        katex_js = _read_text_resource("ui", "vendor", "katex", "katex.min.js")
        auto_render_js = _read_text_resource("ui", "vendor", "katex", "auto-render.min.js")
        scripts = f"""
            <script>{katex_js}</script>
            <script>{auto_render_js}</script>
            <script>
                document.addEventListener("DOMContentLoaded", function() {{
                    if (window.katex) {{
                        document.querySelectorAll(".math-display, .math-inline").forEach(function(node) {{
                            katex.render(node.textContent, node, {{
                                displayMode: node.dataset.display === "true",
                                throwOnError: false
                            }});
                        }});
                    }}
                    if (window.renderMathInElement) {{
                        window.renderMathInElement(document.body, {{
                            throwOnError: false,
                            delimiters: [
                                {{left: "$$", right: "$$", display: true}},
                                {{left: "\\\\[", right: "\\\\]", display: true}},
                                {{left: "$", right: "$", display: false}},
                                {{left: "\\\\(", right: "\\\\)", display: false}}
                            ]
                        }});
                    }}
                }});
            </script>
        """
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<style>{_document_css(theme_name)}</style>"
        "</head><body>"
        f"{html_body}"
        f"{scripts}"
        "</body></html>"
    )


class MarkdownViewer(QWidget):
    """Reusable read-only Markdown + LaTeX viewer."""

    def __init__(self, parent=None):
        """Create the browser renderer or a QTextBrowser fallback."""
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setProperty("role", "markdownViewer")
        self._markdown_text = ""
        self._empty_message = "(No content returned.)"
        self._uses_web_engine = QWebEngineView is not None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if self._uses_web_engine:
            self._view = QWebEngineView(self)
        else:
            self._view = QTextBrowser(self)
            self._view.setOpenExternalLinks(True)
            self._view.setReadOnly(True)
            self._view.setTextInteractionFlags(
                Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard | Qt.LinksAccessibleByMouse
            )
        self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._view, 1)

    def set_markdown(self, text, empty_message="(No content returned.)"):
        """Store response Markdown and render it using the active theme."""
        self._markdown_text = text or ""
        self._empty_message = empty_message
        self._render_current_markdown()

    def _render_current_markdown(self):
        """Rebuild the current document for the selected renderer backend."""
        text = self._markdown_text
        if not text or not text.strip():
            html_body = f"<p>{escape(self._empty_message)}</p>"
        else:
            html_body = render_markdown_to_html(text, web_math=self._uses_web_engine)

        document = build_markdown_document(html_body, include_scripts=self._uses_web_engine)
        if self._uses_web_engine:
            self._view.setHtml(document, QUrl.fromLocalFile(resource_path()))
        else:
            self._view.setHtml(document)

    def apply_theme(self, _resolved_theme):
        """Re-render content after the application theme changes."""
        self._render_current_markdown()
