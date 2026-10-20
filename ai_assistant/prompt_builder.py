"""
PromptBuilder: combines the CircuitTranslator output with an
AnalysisRequest to produce the final AI prompt.

Structure:
    <system prompt>

    Circuit:
    <circuit translation: Source: / Nodes: / Components:>

    Target:
    <selected analysis task, in plain language>

    Instructions:
    <fixed EE1 solving guidance and safety rules>

Only user-facing text belongs in the generated prompt -- no internal
developer/project notes.
"""

from ai_assistant.analysis_request import AnalysisMode

SYSTEM_PROMPT = """You are a Principles of Electrical Engineering I circuit analysis assistant.

Rules:
- Use only the provided circuit data.
- Do not invent missing values.
- Do not modify topology.
- Verify if enough information exists.
- Use KVL, KCL, Mesh, Nodal Analysis, or Superposition as requested.
- Show the original circuit equations before numerical answers.
- Write like an engineering textbook solution manual, not a conversational tutor.
- Keep calculations numerically consistent and avoid intermediate rounding.
- Use plain engineering notation only; do not use LaTeX or math formatting commands."""

FULL_ANALYSIS_SYSTEM_PROMPT = """You are a Principles of Electrical Engineering I circuit analysis assistant.

Rules:
- Use only the provided circuit data.
- Do not invent missing values or modify topology.
- Calculate and verify the complete circuit internally.
- Return only compact final results; do not output equations, derivations, explanations, or conversational text.
- Keep calculations numerically consistent and avoid intermediate rounding.
- Use plain engineering notation only; do not use LaTeX or math formatting commands."""

INSTRUCTIONS_TEXT = """Analyze using Principles of Electrical Engineering I.

Rules:
- Do not modify topology.
- Do not assume missing values.
- If insufficient information exists, explain why mathematically.
- Honor the user's preferred solving method when specified; otherwise select a suitable method based on the circuit structure."""

FULL_ANALYSIS_INSTRUCTIONS_TEXT = """Analyze the complete circuit using Principles of Electrical Engineering I.

Calculate all requested quantities and perform consistency checks internally. Output only the verified results."""

NUMERICAL_PRECISION_TEXT = """Numerical precision rules:
- Do not round intermediate values.
- Keep exact fractions and symbolic expressions whenever practical.
- If decimal conversion is necessary during calculations, preserve at least 8 decimal places.
- Round only final reported numerical answers.
- Final numerical answers must be shown to exactly 4 decimal places.
- Do not repeatedly round values between calculation steps.
- Use the unrounded internal value when calculating later quantities such as currents and powers.
- Do not print 10 decimal places in ordinary explanation text unless that precision is required for verification.

Example:
- Incorrect: 1/52 = 0.0192, then using 0.0192 in later equations.
- Correct: keep 1/52 symbolically, or use 0.0192307692 internally, then show a requested final value as 0.0192."""

TEXTBOOK_STYLE_TEXT = """Textbook-style explanation rules:
- Use plain unnumbered section titles. The result renderer adds display numbering.
- Use structured sections, not conversational scratchwork.
- Preferred sections:
  Chosen Analysis Method
  Known Values and Reference Node
  Circuit Constraints
  KCL/KVL Equations
  Solve the Equations
  Requested Quantity
  Verification
  Final Interpretation
- Explain engineering decisions: method choice, reference node choice, supernodes, source polarity, assumed current direction, and negative-sign interpretation.
- Use plain engineering notation for all equations and mathematical variables/values.
- Do not explain elementary algebra such as multiplying both sides, moving terms, dividing by a coefficient, or expanding obvious brackets.
- Do not include conversational phrases such as "Let's now", "We need to", "Now multiply", "Rearrange", "Self-correction", or "Looking again"."""

EQUATION_FORMAT_TEXT = """Equation formatting rules:
- Output plain text equations only.
- Do not output LaTeX.
- Do not output raw backslashes for mathematical formatting.
- Do not output:
  - \\[
  - \\]
  - \\(
  - \\)
  - \\frac
  - \\mathrm
  - \\tag
  - any other LaTeX command
- Place each major equation on separate lines or blocks.
- Avoid placing long equations inside prose paragraphs.
- Keep equations symbolic as long as possible.
- Use compact plain variable names:
  VA, VD, VE, VF
  IR1, IR2, IV2
  PR1, PV2
- Do not use LaTeX-style subscripts such as V_A, I_{R1}, or P_{V2}.
- Use normal units: V, A, mA, W, mW, Ω.
- Use readable slash notation with spaces around division:
  Correct: (VA - VD) / R1
  Correct: 767 / 105
  Correct: (VA - VD)^2 / R1
  Correct: 808 / (105 × 32)
  Incorrect: (VA - VD)/(R1)
  Incorrect: (767)/(105)
- Use × for multiplication when it improves readability.
- Write powers as x^2 or (VA - VD)^2.
- Do not write squared terms as ((VA - VD)2).
- Example equation:
  PR1
  =
  (VA - VD)^2 / R1
  =
  1.0261 W
- Example KCL layout:
  KCL at Node A:

  (VA - VD) / R1
  + (VA - VE) / R2
  + I1
  = 0

  Substituting values:

  (VA - VD) / 52
  + (VA - VE) / 32
  + 0.1
  = 0

  Simplified:

  84VA - 32VD - 52VE = -166.4
- For each major equation, show only:
  1. the original circuit equation;
  2. substitution of known values;
  3. the final simplified equation;
  4. the solved result.
- Skip unnecessary reciprocal expansions unless the reciprocal value is itself requested.
- Target a concise first-year EE explanation: complete, but about 40-50% shorter than a verbose step-by-step derivation."""

FINAL_ANSWER_TEXT = """Final answer rules:
- Put final requested values only in the SOLUTION section.
- All requested final values must use exactly 4 decimal places.
- Include units, sign, consistent variable names, and actual current direction when relevant.
- For source power, state whether the source supplies or absorbs power.
- Use passive sign convention consistently:
  P > 0 means absorbed.
  P < 0 means supplied.
- Do not call a source "absorbing" when the reported signed power is negative."""

POWER_VERIFICATION_TEXT = """Power verification rules:
- For complete circuit analysis, include a concise power-balance check.
- Use passive sign convention consistently.
- For each source:
  1. State the assumed current direction.
  2. State whether that current enters or leaves the positive terminal.
  3. Then calculate signed power.
- Do not change the sign interpretation after calculating the value.
- Verify power by calculating signed component powers:
  Sum of signed powers = 0
- Do not separately add supplied power as positive and then combine it with absorbed powers as though all signs were positive.
- Use full-precision internal values for the calculation.
- Never claim power conservation is satisfied if supplied and absorbed totals disagree beyond tolerance.
- Use tolerance: abs(sum_P) <= max(1e-6, 0.0001 * total_abs_power).
- If verification fails, recheck current directions, source signs, and arithmetic.
- If verification still fails, explicitly report verification failure.
- Never blame the circuit definition when KCL/KVL equations are sufficient.
- Never attribute a significant discrepancy to rounding without proving it.
- Round only the displayed totals to exactly 4 decimal places.
- Then state either:
  Power conservation satisfied.
  or
  Power mismatch detected; recheck calculations."""

SYMBOLIC_SOLVING_TEXT = """Important:
This is symbolic EE problem solving, not SPICE simulation.

Any component marked solve_target:true is the unknown variable requested by the problem.

Do not treat it as missing information.

Represent unknown targets as algebraic variables and solve using circuit laws."""

RESPONSE_FORMAT_TEXT = """Return your response EXACTLY using this structure:

<SOLUTION>

Put only compact final results here.
Do not include derivations in SOLUTION.

Include:
- requested value
- sign
- magnitude
- actual direction if current
- units
- exactly 4 decimal places for final numerical values
- source power supplied/absorbed interpretation when relevant

Example:

VI1 = -6.8952 V

Polarity:
Node F is 6.8952 V above Node A.

</SOLUTION>

<EXPLANATION>

Put the full EE solving process here.

Include:
- structured textbook derivation
- chosen analysis method and why it is appropriate
- known values and reference node
- circuit constraints
- KCL/KVL equations
- substitutions and simplified equations
- solved results using unrounded internal values
- verification, including power balance for complete circuit analysis
- final interpretation

Do not repeat the compact SOLUTION content inside EXPLANATION.
Do not add a separate Final Answers section inside EXPLANATION.

Example:

Chosen Analysis Method

Nodal analysis is selected because the circuit contains a current source and
a voltage source between two non-reference nodes.

Known Values and Reference Node

R1 = 52 Ω
R2 = 32 Ω
R3 = 126 Ω
R4 = 63 Ω
I1 = 0.1 A
V2 = 15 V

Choose Node F as reference:

VF = 0 V

Circuit Constraints

VE - VD = 15

KCL/KVL Equations

KCL at Node A:

(VA - VD) / 52
+ (VA - VE) / 32
+ 0.1
= 0

Supernode equation:

(VD - VA) / 52
+ VD / 126
+ (VE - VA) / 32
+ VE / 63
= 0

Solve the Equations

VA = -724 / 105
VD = -71 / 5
VE = 4 / 5

Final decimal values:

VA = -6.8952 V
VD = -14.2000 V
VE = 0.8000 V

Requested Quantity

VI1 = VA - VF

VI1 = -6.8952 V

</EXPLANATION>"""

FULL_ANALYSIS_RESPONSE_FORMAT_TEXT = """Complete circuit analysis output rules:
- Return results only. Do not include explanations, derivations, equations, method-selection commentary, or conversational text.
- Include all node voltages, all branch currents, signed power for every component, and the power-balance result.
- Use exactly 4 decimal places for final numerical values and include units.
- Return exactly one tagged section using this structure:

<SOLUTION>

Put the complete set of compact final results here.

</SOLUTION>

Do not return an EXPLANATION section."""


def build_ai_prompt(circuit_export_text, analysis_request):
    """
    Combine circuit data and the user's AnalysisRequest into the final
    AI prompt text.

    Args:
        circuit_export_text: str, output of circuit_translator.generate_circuit_export()
        analysis_request: AnalysisRequest describing what to solve for

    Returns:
        str: the full prompt to send to (or copy into) an AI assistant.
    """
    is_full_analysis = analysis_request.mode == AnalysisMode.FULL_ANALYSIS
    common_sections = [
        FULL_ANALYSIS_SYSTEM_PROMPT if is_full_analysis else SYSTEM_PROMPT,
        "",
        circuit_export_text.rstrip(),
        "",
        "",
        "Target:",
        analysis_request.to_prompt_section(),
        "",
        "",
        "Instructions:",
        FULL_ANALYSIS_INSTRUCTIONS_TEXT if is_full_analysis else INSTRUCTIONS_TEXT,
        "",
        "",
        NUMERICAL_PRECISION_TEXT,
    ]
    if is_full_analysis:
        sections = common_sections + [
            "",
            "",
            FINAL_ANSWER_TEXT,
            "",
            "",
            POWER_VERIFICATION_TEXT,
            "",
            "",
            SYMBOLIC_SOLVING_TEXT,
            "",
            "",
            FULL_ANALYSIS_RESPONSE_FORMAT_TEXT,
        ]
    else:
        sections = common_sections + [
            "",
            "",
            TEXTBOOK_STYLE_TEXT,
            "",
            "",
            EQUATION_FORMAT_TEXT,
            "",
            "",
            FINAL_ANSWER_TEXT,
            "",
            "",
            POWER_VERIFICATION_TEXT,
            "",
            "",
            SYMBOLIC_SOLVING_TEXT,
            "",
            "",
            RESPONSE_FORMAT_TEXT,
        ]
    return "\n".join(sections).rstrip() + "\n"
