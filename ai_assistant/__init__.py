"""
AI-assisted circuit analysis package.

Pipeline:
    Circuit GUI -> Validation Engine -> Circuit Translator -> AI Prompt
    Generator -> AI Provider Interface -> Result Display

This package never feeds AI output back into the circuit model; it is a
read-only analysis/explanation layer on top of the existing GUI, wiring
validation, and topology detection.
"""
