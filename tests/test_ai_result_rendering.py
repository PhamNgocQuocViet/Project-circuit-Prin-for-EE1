"""Regression tests for AI response splitting and safe Markdown rendering."""

import unittest

from ai_assistant.markdown_viewer import build_markdown_document, render_markdown_to_html
from ai_assistant.result_formatter import (
    canonicalize_heading,
    format_explanation_sections,
    normalize_equation_operators,
)
from ai_assistant.result_dialog import (
    FALLBACK_EXPLANATION_TEXT,
    split_solution_and_explanation,
)


class ResultSplitTests(unittest.TestCase):
    def test_valid_tagged_response(self):
        solution, explanation = split_solution_and_explanation(
            "<SOLUTION>VA = 1 V</SOLUTION><EXPLANATION>Use KCL.</EXPLANATION>"
        )
        self.assertEqual(solution, "VA = 1 V")
        self.assertEqual(explanation, "Use KCL.")

    def test_missing_closing_tag_recovers_until_next_tag(self):
        solution, explanation = split_solution_and_explanation(
            "<SOLUTION>VA = 1 V\n<EXPLANATION>KCL steps"
        )
        self.assertEqual(solution, "VA = 1 V")
        self.assertEqual(explanation, "KCL steps")

    def test_only_solution_present(self):
        solution, explanation = split_solution_and_explanation(
            "<SOLUTION>IR1 = 0.1000 A</SOLUTION>"
        )
        self.assertEqual(solution, "IR1 = 0.1000 A")
        self.assertEqual(explanation, FALLBACK_EXPLANATION_TEXT)

    def test_only_explanation_present(self):
        solution, explanation = split_solution_and_explanation(
            "<EXPLANATION>Full derivation</EXPLANATION>"
        )
        self.assertEqual(solution, "")
        self.assertEqual(explanation, "Full derivation")

    def test_extra_text_before_after_tags_does_not_leak_tags(self):
        solution, explanation = split_solution_and_explanation(
            "Before\n<SOLUTION>Answer</SOLUTION>\n<EXPLANATION>Steps</EXPLANATION>\nAfter"
        )
        self.assertEqual(solution, "Answer")
        self.assertEqual(explanation, "Steps")
        self.assertNotIn("<SOLUTION>", solution + explanation)
        self.assertNotIn("<EXPLANATION>", solution + explanation)

    def test_explaination_typo_supported(self):
        solution, explanation = split_solution_and_explanation(
            "<SOLUTION>Answer</SOLUTION><EXPLAINATION>Typo tag</EXPLAINATION>"
        )
        self.assertEqual(solution, "Answer")
        self.assertEqual(explanation, "Typo tag")


class MarkdownRenderTests(unittest.TestCase):
    def test_very_long_equation_renders_without_crash_or_tags(self):
        equation = " + ".join(f"(VA - V{i}) / {i + 1}" for i in range(80)) + " = 0"
        html = render_markdown_to_html(equation, web_math=False)
        self.assertIn("math-display-fallback", html)
        self.assertNotIn("<SOLUTION>", html)

    def test_unicode_symbols_survive(self):
        html = render_markdown_to_html("R1 = 52 Ω\nP ≈ 1.2500 W", web_math=False)
        self.assertIn("Ω", html)
        self.assertIn("≈", html)

    def test_empty_response(self):
        self.assertEqual(render_markdown_to_html("", web_math=False), "")

    def test_malformed_markdown_is_readable(self):
        html = render_markdown_to_html("### Heading\n- bullet\n**unterminated", web_math=False)
        self.assertIn("Heading", html)
        self.assertIn("bullet", html)

    def test_mixed_headings_and_bullet_lists(self):
        html = render_markdown_to_html("### KCL\n- Node A\n- Supernode", web_math=False)
        self.assertIn("KCL", html)
        self.assertIn("Node A", html)
        self.assertIn("Supernode", html)

    def test_plain_text_fraction_does_not_leak_internal_html(self):
        html = render_markdown_to_html(r"IR1 is \(767 / 105\) A", web_math=False)
        self.assertNotIn("&lt;span", html)
        self.assertNotIn('class="eq-frac">', html)
        self.assertIn("767 / 105", html)

    def test_display_fraction_fallback_uses_readable_slash_not_tiny_inline_fraction(self):
        html = render_markdown_to_html("(VA - VD) / R1 + 767 / 105 = 0", web_math=False)
        self.assertIn('class="equation-block"', html)
        self.assertIn("(V<sub>A</sub> − V<sub>D</sub>) / R1", html)
        self.assertIn("767 / 105", html)
        self.assertNotIn("eq-frac-inline", html)

    def test_raw_latex_commands_not_visible_in_fallback(self):
        html = render_markdown_to_html(r"\[\frac{VA - VD}{R1} = 0\]", web_math=False)
        self.assertNotIn(r"\frac", html)
        self.assertNotIn(r"\[", html)

    def test_raw_response_tags_removed_by_renderer(self):
        html = render_markdown_to_html("<SOLUTION>VA = 1 V</SOLUTION>", web_math=False)
        self.assertNotIn("<SOLUTION>", html)
        self.assertNotIn("</SOLUTION>", html)
        self.assertIn("V<sub>A</sub> = 1 V", html)


class ExplanationHeadingFormatTests(unittest.TestCase):
    def assert_steps_1_and_2(self, text):
        formatted = format_explanation_sections(text)
        self.assertIn('<h2 class="solution-step">Step 1. Chosen Analysis Method</h2>', formatted)
        self.assertIn(
            '<h2 class="solution-step">Step 2. Known Values and Reference Node</h2>',
            formatted,
        )
        self.assertNotIn(">1. Chosen Analysis Method<", formatted)
        self.assertNotIn(">1. Known Values", formatted)

    def test_numbered_major_headings(self):
        self.assert_steps_1_and_2("1. Chosen Analysis Method\n2. Known Values and Reference Node")

    def test_markdown_numbered_major_headings(self):
        self.assert_steps_1_and_2(
            "### 1. Chosen Analysis Method\n### 2. Known Values and Reference Node"
        )

    def test_step_numbered_major_headings(self):
        self.assert_steps_1_and_2(
            "Step 1. Chosen Analysis Method\nStep 2. Known Values and Reference Node"
        )

    def test_unnumbered_major_headings(self):
        self.assert_steps_1_and_2("Chosen Analysis Method\nKnown Values and Reference Node")

    def test_bold_numbered_major_heading(self):
        formatted = format_explanation_sections("**1. Chosen Analysis Method:**")
        self.assertIn("Step 1. Chosen Analysis Method", formatted)

    def test_alias_heading(self):
        self.assertEqual(canonicalize_heading("Selected Analysis Method"), "Chosen Analysis Method")
        self.assertEqual(canonicalize_heading("Nodal Equations"), "KCL/KVL Equations")

    def test_real_ordered_list_inside_content_preserved(self):
        html = render_markdown_to_html(
            "Verification checks:\n\n1. KCL at Node A\n2. Power balance",
            web_math=False,
        )
        self.assertIn("<ol>", html)
        self.assertIn("KCL at Node A", html)

    def test_unknown_heading_preserved_as_secondary_heading(self):
        formatted = format_explanation_sections("### Additional Notes\nKeep this content")
        self.assertIn('<h3 class="solution-subheading">Additional Notes</h3>', formatted)
        self.assertIn("Keep this content", formatted)

    def test_final_answer_heading_not_numbered(self):
        formatted = format_explanation_sections("Final Answers\nVA = 1 V")
        self.assertIn("solution-subheading", formatted)
        self.assertNotIn("Step", formatted)

    def test_renderer_generated_h2_not_visible_as_text(self):
        html = render_markdown_to_html("Solve the Equations\nVA = VD + 1", web_math=False)
        self.assertIn('<h2 class="solution-step">Step 5. Solve the Equations</h2>', html)
        self.assertNotIn("&lt;h2", html)
        self.assertNotIn('<p><h2', html)

    def test_equations_render_as_equation_blocks_not_code_blocks(self):
        html = render_markdown_to_html("VA - VD = 767 / 105", web_math=False)
        self.assertIn('class="equation-block"', html)
        self.assertNotIn("<pre>", html)
        self.assertNotIn("<code>", html)

    def test_actual_code_blocks_still_use_code_styling(self):
        html = render_markdown_to_html("```python\nprint('x')\n```", web_math=False)
        self.assertIn("<code", html)
        self.assertIn("print", html)

    def test_equations_inside_code_blocks_are_not_reformatted(self):
        html = render_markdown_to_html("```text\nVA = VD + 1\n```", web_math=False)
        self.assertIn("<code", html)
        self.assertIn("VA = VD + 1", html)
        self.assertNotIn('class="equation-block"', html)

    def test_variable_subscripts_in_equation_blocks(self):
        html = render_markdown_to_html("IR1 + PV2 + VA - VD = 0", web_math=False)
        self.assertIn("I<sub>R1</sub>", html)
        self.assertIn("P<sub>V2</sub>", html)
        self.assertIn("V<sub>A</sub>", html)
        self.assertIn("V<sub>D</sub>", html)

    def test_equation_operator_normalization(self):
        normalized = normalize_equation_operators("VA * VD -> X <= Y >= Z != 0")
        self.assertIn("×", normalized)
        self.assertIn("→", normalized)
        self.assertIn("≤", normalized)
        self.assertIn("≥", normalized)
        self.assertIn("≠", normalized)

    def test_ai_angle_brackets_safely_escaped(self):
        html = render_markdown_to_html("VA < VD means compare > threshold", web_math=False)
        self.assertIn("&lt;", html)
        self.assertIn("&gt;", html)

    def test_equation_css_wraps_and_uses_subtle_theme_colors(self):
        dark_doc = build_markdown_document('<div class="equation-block">VA = VD + 1</div>', theme_name="dark")
        light_doc = build_markdown_document('<div class="equation-block">VA = VD + 1</div>', theme_name="light")
        self.assertIn("white-space: pre-wrap;", dark_doc)
        self.assertIn("overflow-wrap: anywhere;", dark_doc)
        self.assertIn("overflow-x: auto;", dark_doc)
        self.assertIn("background: transparent;", dark_doc)
        self.assertIn("border-left: 3px solid #4F8CC9;", dark_doc)
        self.assertIn("border-left: 3px solid #3B73A8;", light_doc)


if __name__ == "__main__":
    unittest.main()
