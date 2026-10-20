"""
Analysis Request model: describes exactly what the user is asking the AI
to do with the (already validated/translated) circuit.

Three modes are supported:
    FULL_ANALYSIS       -- complete node voltages / branch currents / power
    SOLVE_MISSING_VALUE -- find one component's currently-unknown value
    COMPONENT_ANALYSIS  -- find one specific quantity of one component
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from components.electrical_component import ComponentType


class AnalysisMode(Enum):
    """Supported scopes for an AI circuit-analysis request."""
    FULL_ANALYSIS = "Complete Circuit Analysis"
    SOLVE_MISSING_VALUE = "Solve Missing Component Value"
    COMPONENT_ANALYSIS = "Find Component Quantity"


class SolvingMethod(Enum):
    """User-selected primary method for targeted analysis modes."""

    AUTO = "Auto"
    NODAL = "Nodal Analysis"
    MESH = "Mesh Analysis"
    SUPERPOSITION = "Superposition"
    USER_DEFINED = "User-defined"


# Name of the physical quantity that is "missing" for each component type,
# used to phrase the SOLVE_MISSING_VALUE request.
MISSING_VALUE_QUANTITY = {
    ComponentType.RESISTOR: "resistance",
    ComponentType.CAPACITOR: "capacitance",
    ComponentType.INDUCTOR: "inductance",
    ComponentType.VOLTAGE_SOURCE: "voltage",
    ComponentType.CURRENT_SOURCE: "current",
}

# Quantities the user may ask about for each component type, in
# COMPONENT_ANALYSIS mode.
QUANTITY_OPTIONS_BY_TYPE = {
    ComponentType.RESISTOR: ["Voltage Drop", "Current", "Power", "Resistance"],
    ComponentType.CAPACITOR: ["Voltage", "Current", "Impedance", "Reactance"],
    ComponentType.INDUCTOR: ["Voltage", "Current", "Impedance", "Reactance"],
    ComponentType.VOLTAGE_SOURCE: ["Output Current", "Delivered Power"],
    ComponentType.CURRENT_SOURCE: ["Voltage", "Delivered Power"],
}

# (preposition, plain-language phrase) used to turn a quantity option into a
# short natural-language "Calculate <phrase> <preposition> <ref>" sentence.
QUANTITY_PHRASING = {
    "Voltage Drop": ("across", "voltage drop"),
    "Current": ("through", "current"),
    "Power": ("dissipated by", "power"),
    "Resistance": ("of", "resistance"),
    "Voltage": ("across", "voltage"),
    "Impedance": ("of", "impedance"),
    "Reactance": ("of", "reactance"),
    "Output Current": ("of", "output current"),
    "Delivered Power": ("of", "delivered power"),
}


def _export_ref(ref):
    """Strip the '#' from a canvas reference name for AI-facing text (e.g. 'R#2' -> 'R2')."""
    return (ref or "").replace("#", "")


@dataclass
class AnalysisRequest:
    """What the user wants the AI to determine about the current circuit."""

    mode: AnalysisMode
    target_component: Optional[str] = None          # e.g. "R#2" (reference name)
    target_component_type: Optional[ComponentType] = None
    requested_quantity: Optional[str] = None         # e.g. "Voltage Drop"
    preferred_method: Optional[SolvingMethod] = None
    custom_method: Optional[str] = None

    def to_prompt_section(self):
        """Return the mode-specific 'Target:' body text."""
        if self.mode == AnalysisMode.FULL_ANALYSIS:
            return (
                "Perform a complete analysis of this circuit: find all node voltages, "
                "all branch currents, and the power for every component. Return only the "
                "final results; do not include derivations or explanations."
            )

        ref = _export_ref(self.target_component)

        if self.mode == AnalysisMode.SOLVE_MISSING_VALUE:
            quantity_name = MISSING_VALUE_QUANTITY.get(self.target_component_type, "value")
            target = f"Find the missing {quantity_name} value of {ref}."
            return self._with_preferred_method(target)

        if self.mode == AnalysisMode.COMPONENT_ANALYSIS:
            preposition, phrase = QUANTITY_PHRASING.get(
                self.requested_quantity, ("of", (self.requested_quantity or "value").lower())
            )
            target = f"Calculate {phrase} {preposition} {ref}."
            return self._with_preferred_method(target)

        raise ValueError(f"Unknown analysis mode: {self.mode!r}")

    def _with_preferred_method(self, target):
        """Append the selected solving-method instruction to target text.

        Args:
            target: Base natural-language calculation request.

        Returns:
            The target plus an automatic, predefined, or custom method request.
        """
        if self.preferred_method is None or self.preferred_method == SolvingMethod.AUTO:
            return f"{target}\nSelect the most suitable solving method automatically."
        if self.preferred_method == SolvingMethod.USER_DEFINED:
            custom_method = (self.custom_method or "").strip()
            if not custom_method:
                raise ValueError("A custom solving method is required for User-defined mode.")
            return f"{target}\nUse this user-defined solving method: {custom_method}"
        return f"{target}\nUse {self.preferred_method.value} as the solving method."
