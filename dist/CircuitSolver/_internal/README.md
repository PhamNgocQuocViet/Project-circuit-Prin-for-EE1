# Electrical Engineering Learning App

Desktop learning tool for building simple electrical circuits, checking circuit wiring, exporting/importing circuit files, and generating AI-assisted solving walkthroughs.

Built with Python and PyQt5.

## Features

- Grid-based circuit canvas with snap-to-grid placement.
- Drag-and-drop or click-to-place components.
- Resistor, capacitor, inductor, voltage source, current source, and node components.
- Component references such as `R#1`, `V#2`, and `I#3`.
- Right-click component connections with visible terminal markers.
- Move, rotate, zoom, pan, undo, clear canvas, and center view controls.
- Value panel for placed value-based components.
- Circuit comments panel with missing-value and wiring checks.
- Topology checks for disconnected groups, open circuits, series/parallel structure, and complex mesh/nodal solvability.
- Circuit export/import using `.circuit` or `.json`.
- AI-assisted solving workflow with Solution and Explanation tabs.
- AI result renderer with Markdown, readable engineering equations, and local KaTeX-compatible assets.
- Multi-provider AI settings:
  - Ollama Local
  - Gemini
  - OpenAI
  - NVIDIA AI
  - Custom/OpenAI-compatible endpoint
- Dark, light, and system theme modes.

## Requirements

- Python 3.10 or newer recommended.
- pip.
- Windows recommended for packaged release builds.

Python packages are listed in [requirements.txt](requirements.txt):

```text
PyQt5
PyQt5-sip
PyQtWebEngine
Markdown
keyring
```

`PyQtWebEngine` is used by the AI result viewer. If unavailable, the app falls back to a QTextBrowser-based renderer.

## Setup

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

The app opens with:

- left panel: components, actions, comments
- center: circuit canvas
- right panel: component values

## Basic Use

1. Select a component from the left panel.
2. Place it on the canvas by clicking the grid or dragging from the component list.
3. Enter values in the right panel.
4. Right-click one component, then right-click another component to create a wire.
5. Use `R` to rotate selected components.
6. Use the mouse wheel to zoom.
7. Hold middle mouse button to pan.
8. Use `Undo (Ctrl+Z)` to undo component placement or wiring.
9. Use `Export` and `Import` for saved circuits.
10. Use `Solve Circuit` for AI-assisted solving.

## AI Solving

`Solve Circuit` validates the circuit first. If wiring is valid, the app asks for the desired analysis mode:

- Complete Circuit Analysis
- Solve Missing Component Value
- Find Component Quantity

The circuit is converted into a structured text prompt and sent to the selected AI provider.

If no provider is configured, or the request fails, the app shows the generated prompt in a manual copy dialog.

AI output never changes circuit topology or component values. It is displayed only.

## AI Settings

Open `Settings` > `AI`.

Provider notes:

- `Ollama Local`: default local provider, no API key needed, requires Ollama running locally.
- `Gemini`: requires Gemini API key.
- `OpenAI`: uses the official OpenAI Responses API and requires an OpenAI API key.
- `NVIDIA AI`: requires NVIDIA API key.
- `Custom`: OpenAI-compatible Chat Completions endpoint.

API keys are saved with secure storage when available. Non-secret provider settings are saved locally through Qt settings.

## Project Structure

```text
.
├── main.py
├── app_paths.py
├── requirements.txt
├── CircuitSolver.spec
├── LICENSE
├── README.md
├── components/
│   ├── __init__.py
│   ├── component_factory.py
│   ├── electrical_component.py
│   └── unit_scales.py
├── circuit_engine/
│   ├── circuit_checks/
│   │   ├── __init__.py
│   │   ├── analyzer.py
│   │   ├── mesh_nodal.py
│   │   ├── netlist.py
│   │   ├── series_parallel.py
│   │   ├── solvability.py
│   │   └── wiring_checks.py
│   └── io/
│       ├── circuit_importer.py
│       └── circuit_serializer.py
├── ai_assistant/
│   ├── __init__.py
│   ├── ai_request_worker.py
│   ├── analysis_dialog.py
│   ├── analysis_request.py
│   ├── circuit_translator.py
│   ├── markdown_viewer.py
│   ├── prompt_builder.py
│   ├── providers.py
│   ├── result_dialog.py
│   ├── result_formatter.py
│   ├── settings_dialog.py
│   └── settings_manager.py
├── ai_engine/
│   ├── __init__.py
│   ├── model_discovery.py
│   └── model_filters.py
├── ui/
│   ├── __init__.py
│   ├── canvas.py
│   ├── main_window.py
│   ├── resolution_manager.py
│   ├── theme_manager.py
│   ├── dialogs/
│   │   ├── __init__.py
│   │   ├── ai_loading_dialog.py
│   │   └── settings_dialog.py
│   ├── settings_pages/
│   │   ├── __init__.py
│   │   ├── about_page.py
│   │   ├── ai_settings_page.py
│   │   ├── appearance_settings_page.py
│   │   └── general_settings_page.py
│   ├── styles/
│   │   ├── dark.qss
│   │   └── light.qss
│   └── vendor/
│       └── katex/
├── circuit_exports/              # Bundled example and saved .circuit files
├── Release_Versions/             # Archived release packages
└── tests/
    ├── test_ai_result_rendering.py
    ├── test_analysis_options.py
    ├── test_component_schematic.py
    ├── test_component_units.py
    ├── test_existing_circuit_exports.py
    └── test_resolution_manager.py
```

`ai_assistant/settings_dialog.py` is a compatibility wrapper that re-exports the modular settings dialog.

## Packaging

`CircuitSolver.spec` is the PyInstaller build recipe. Keep it if you need release builds.

It tells PyInstaller to:

- use `main.py` as the entry point
- create a windowed app named `CircuitSolver`
- bundle theme QSS files
- bundle local KaTeX-compatible renderer assets
- bundle sample/exported circuit files from `circuit_exports`
- include hidden imports for Qt WebEngine and keyring credential storage

Build command:

```powershell
.\.venv\Scripts\pyinstaller.exe CircuitSolver.spec
```

Generated output:

- `build/`: temporary PyInstaller build files; safe to delete after packaging.
- `dist/CircuitSolver/`: runnable packaged app folder.
- `dist/*.rar` and `Release_Versions/*.rar`: release archives; review before deleting.

## Generated Files

Safe cleanup targets:

- `__pycache__/`
- `*.pyc`
- `build/`

Review before deleting:

- `dist/CircuitSolver/`
- `dist/*.rar`
- `Release_Versions/*.rar`
- `circuit_exports/*.circuit`

## Tests

Run renderer tests:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_ai_result_rendering
```

## Current Limitations

- Circuit solving is AI-assisted; the app does not apply AI results back into circuit values.
- AC phasor analysis is not implemented.
- Delete/redo controls are future enhancements.
- Wire routing is direct-line based.

## Project Members

HCMIU, Vietnam National University:

- Phạm Ngọc Quốc Việt - EEEESB24010
- Nguyên Anh Quân - EEACIU25049
- Ngô Phan Minh Quân - EEACIU25050
- Nguyên Lê Minh Quân - EEACIU25051
- Hoàng Bá Minh Quân - EEACIU25052

## License

Copyright 2026 Phạm Ngọc Quốc Việt, Nguyên Anh Quân, Ngô Phan Minh Quân, Nguyên Lê Minh Quân, and Hoàng Bá Minh Quân.

Distributed free of charge under the custom [CircuitSolver Source-Available Freeware License](LICENSE). The source may be inspected and privately modified, but selling or redistributing the original or modified software requires prior written permission from the copyright holders.

Because these restrictions do not satisfy the Open Source Initiative's free-redistribution requirement, CircuitSolver is accurately described as **source-available freeware**, not OSI-approved open-source software.
