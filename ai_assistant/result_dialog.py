"""
Result Display: read-only viewers for the AI response (Solution /
Explanation tabs), plus the manual-fallback prompt dialog with a Copy
button used when no AI provider is configured or reachable.

Neither dialog ever writes AI output back into the circuit model -- both
are purely for display/copy.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPlainTextEdit, QPushButton, QLabel, QApplication, QSizePolicy,
)
from PyQt5.QtCore import Qt

import re

from ai_assistant.markdown_viewer import MarkdownViewer

SOLUTION_TAG_RE = re.compile(
    r"<\s*SOLUTION\s*>(.*?)<\s*/\s*SOLUTION\s*>",
    re.IGNORECASE | re.DOTALL,
)
EXPLANATION_TAG_RE = re.compile(
    r"<\s*EXPLAI?NATION\s*>(.*?)<\s*/\s*EXPLAI?NATION\s*>",
    re.IGNORECASE | re.DOTALL,
)
RESPONSE_TAG_RE = re.compile(
    r"<\s*(/)?\s*(SOLUTION|EXPLAI?NATION)\s*>",
    re.IGNORECASE,
)

FALLBACK_EXPLANATION_TEXT = "AI response was not formatted correctly."


def _remove_match(text, match):
    """Remove one regex match from text while preserving surrounding text."""
    return (text[: match.start()] + text[match.end() :]).strip()


def _strip_response_tags(text):
    """Remove common leftover response tags from recovered content."""
    return RESPONSE_TAG_RE.sub("", text or "").strip()


def _canonical_tag(raw_tag):
    """Normalize supported response-section tag spellings."""
    tag = (raw_tag or "").strip().upper()
    if tag == "SOLUTION":
        return "solution"
    if tag in {"EXPLANATION", "EXPLAINATION"}:
        return "explanation"
    return ""


def _extract_tagged_sections(text):
    """Recover tagged sections, including missing closing tags."""
    sections = {"solution": [], "explanation": []}
    outside_ranges = []
    matches = list(RESPONSE_TAG_RE.finditer(text))
    if not matches:
        return sections, text.strip()

    cursor = 0
    index = 0
    while index < len(matches):
        match = matches[index]
        if match.start() > cursor:
            outside_ranges.append((cursor, match.start()))
        cursor = match.end()

        is_close = bool(match.group(1))
        tag_name = _canonical_tag(match.group(2))
        if is_close or not tag_name:
            index += 1
            continue

        content_start = match.end()
        content_end = len(text)
        next_index = index + 1
        while next_index < len(matches):
            next_match = matches[next_index]
            next_is_close = bool(next_match.group(1))
            next_tag = _canonical_tag(next_match.group(2))
            if next_is_close and next_tag == tag_name:
                content_end = next_match.start()
                cursor = next_match.end()
                next_index += 1
                break
            if not next_is_close and next_tag in sections:
                content_end = next_match.start()
                cursor = next_match.start()
                break
            next_index += 1

        content = _strip_response_tags(text[content_start:content_end])
        if content:
            sections[tag_name].append(content)
        index = max(next_index, index + 1)

    if cursor < len(text):
        outside_ranges.append((cursor, len(text)))

    outside_text = "\n\n".join(
        _strip_response_tags(text[start:end])
        for start, end in outside_ranges
        if _strip_response_tags(text[start:end])
    ).strip()
    return sections, outside_text


def split_solution_and_explanation(ai_text):
    """
    Extract the <SOLUTION>...</SOLUTION> and <EXPLANATION>...</EXPLANATION>
    tagged sections from a raw AI response.

    Tags may contain whitespace/case variations and surrounding text.
    If only one section exists, recover that section instead of discarding
    the whole response.
    """
    if not ai_text:
        return "", ""

    clean_text = str(ai_text).strip()
    sections, outside_text = _extract_tagged_sections(clean_text)
    solution_text = "\n\n".join(sections["solution"]).strip()
    explanation_text = "\n\n".join(sections["explanation"]).strip()

    if solution_text and explanation_text:
        return solution_text, explanation_text
    if solution_text:
        return solution_text, outside_text or FALLBACK_EXPLANATION_TEXT
    if explanation_text:
        return outside_text, explanation_text
    return _strip_response_tags(clean_text), FALLBACK_EXPLANATION_TEXT


class ResultDialog(QDialog):
    """Displays the AI's circuit analysis in Solution / Explanation tabs."""

    def __init__(self, solution_text, explanation_text, parent=None, show_explanation=True):
        """Build read-only result tabs.

        Args:
            solution_text: AI solution or final-results Markdown.
            explanation_text: Optional explanatory Markdown.
            parent: Optional owning Qt widget.
            show_explanation: Whether to create the Explanation tab.
        """
        super().__init__(parent)
        self.setWindowTitle("AI Circuit Analysis Result")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.resize(1000, 720)
        self.setMinimumSize(700, 500)
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        solution_view = MarkdownViewer()
        solution_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        solution_view.set_markdown(solution_text, "(No solution content returned.)")
        self.tabs.addTab(solution_view, "Solution")

        if show_explanation:
            explanation_view = MarkdownViewer()
            explanation_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            explanation_view.set_markdown(explanation_text, "(No explanation content returned.)")
            self.tabs.addTab(explanation_view, "Explanation")

        layout.addWidget(self.tabs, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class ManualPromptDialog(QDialog):
    """Manual fallback: show the generated prompt with a Copy button."""

    def __init__(self, prompt_text, parent=None):
        """Display a provider-ready prompt that the user can copy manually."""
        super().__init__(parent)
        self.setWindowTitle("Manual AI Prompt")
        self.resize(720, 560)
        self.setMinimumSize(560, 420)

        layout = QVBoxLayout(self)

        info_label = QLabel("Copy this prompt into your preferred AI assistant")
        info_label.setProperty("role", "sectionTitle")
        layout.addWidget(info_label)

        self.prompt_view = QPlainTextEdit()
        self.prompt_view.setReadOnly(True)
        self.prompt_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.prompt_view.setPlainText(prompt_text)
        layout.addWidget(self.prompt_view, 1)

        button_row = QHBoxLayout()
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self.copy_prompt)
        button_row.addWidget(copy_btn)
        button_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)

        layout.addLayout(button_row)

    def copy_prompt(self):
        """Copy the complete prompt to the application clipboard."""
        QApplication.clipboard().setText(self.prompt_view.toPlainText())
