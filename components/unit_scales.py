"""Selectable engineering unit scales for value-bearing components."""

from dataclasses import dataclass

from components.electrical_component import ComponentType


@dataclass(frozen=True)
class UnitOption:
    """One user-facing engineering-unit label and its compact symbol."""
    label: str
    symbol: str


UNIT_OPTIONS = {
    ComponentType.RESISTOR: (
        UnitOption("Milliohm (mΩ)", "mΩ"),
        UnitOption("Ohm (Ω)", "Ω"),
        UnitOption("Kiloohm (kΩ)", "kΩ"),
        UnitOption("Megaohm (MΩ)", "MΩ"),
    ),
    ComponentType.CAPACITOR: (
        UnitOption("Picofarad (pF)", "pF"),
        UnitOption("Nanofarad (nF)", "nF"),
        UnitOption("Microfarad (µF)", "µF"),
        UnitOption("Millifarad (mF)", "mF"),
        UnitOption("Farad (F)", "F"),
    ),
    ComponentType.INDUCTOR: (
        UnitOption("Nanohenry (nH)", "nH"),
        UnitOption("Microhenry (µH)", "µH"),
        UnitOption("Millihenry (mH)", "mH"),
        UnitOption("Henry (H)", "H"),
    ),
    ComponentType.VOLTAGE_SOURCE: (
        UnitOption("Millivolt (mV)", "mV"),
        UnitOption("Volt (V)", "V"),
        UnitOption("Kilovolt (kV)", "kV"),
    ),
    ComponentType.CURRENT_SOURCE: (
        UnitOption("Microampere (µA)", "µA"),
        UnitOption("Milliampere (mA)", "mA"),
        UnitOption("Ampere (A)", "A"),
        UnitOption("Kiloampere (kA)", "kA"),
    ),
}

BASE_UNIT_SYMBOLS = {
    ComponentType.RESISTOR: "Ω",
    ComponentType.CAPACITOR: "F",
    ComponentType.INDUCTOR: "H",
    ComponentType.VOLTAGE_SOURCE: "V",
    ComponentType.CURRENT_SOURCE: "A",
}

LEGACY_UNIT_ALIASES = {
    "Ohm (Ω)": "Ω",
    "Farad (F)": "F",
    "Henry (H)": "H",
    "Volt (V)": "V",
    "Ampere (A)": "A",
}


def options_for_component(comp_type):
    """Return selectable UnitOption values for a ComponentType."""
    return UNIT_OPTIONS.get(comp_type, ())


def normalize_unit_symbol(comp_type, unit):
    """Return a valid symbol, falling back to the component's base unit."""
    raw_unit = str(unit or "").strip()
    raw_unit = LEGACY_UNIT_ALIASES.get(raw_unit, raw_unit)
    valid_symbols = {option.symbol for option in options_for_component(comp_type)}
    if raw_unit in valid_symbols:
        return raw_unit
    return BASE_UNIT_SYMBOLS.get(comp_type, "")
