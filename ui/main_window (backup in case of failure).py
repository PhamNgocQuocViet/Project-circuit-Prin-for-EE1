"""Coordinate the application's main window and its top-level workflows.

The window owns the component palette, circuit canvas, value editor, settings
entry points, import/export actions, and asynchronous AI-analysis lifecycle.
Circuit drawing and validation remain delegated to their dedicated modules.
"""

import os
from html import escape

from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                             QPushButton, QListWidget, QListWidgetItem, QLabel,
                             QComboBox, QLineEdit, QFormLayout, QScrollArea, QFrame, QSplitter, QSizePolicy, QLayout,
                             QMessageBox, QFileDialog, QApplication, QDialog, QTextBrowser)
from PyQt5.QtCore import Qt, QMimeData, QThread, QTimer
from PyQt5.QtGui import QDrag

from app_paths import resource_path
from components.component_factory import ComponentFactory
from components.electrical_component import ComponentType
from components.unit_scales import normalize_unit_symbol, options_for_component
from circuit_engine.circuit_checks import analyze_circuit
from circuit_engine.circuit_checks.netlist import build_nets
from circuit_engine.circuit_checks.wiring_checks import is_value_component, run_wiring_checks
from ui.canvas import CircuitCanvas
from circuit_engine.io.circuit_serializer import serialize_circuit, serialize_to_json, deserialize_from_json
from circuit_engine.io.circuit_importer import reconstruct_circuit_from_dict
from ai_assistant.circuit_translator import generate_circuit_export
from ai_assistant.prompt_builder import build_ai_prompt
from ai_assistant.ai_request_worker import AIRequestWorker
from ai_assistant.settings_manager import (
    load_settings, is_configured, is_first_launch, mark_first_launch_seen,
)
from ai_assistant.providers import create_provider
from ui.dialogs.settings_dialog import SettingsDialog
from ui.dialogs.ai_loading_dialog import AILoadingDialog
from ui.resolution_manager import ResolutionManager
from ai_assistant.analysis_dialog import AnalysisDialog
from ai_assistant.analysis_request import AnalysisMode
from ai_assistant.result_dialog import ResultDialog, ManualPromptDialog, split_solution_and_explanation

class ComponentListWidget(QListWidget):
    """List widget that supports dragging component types to the canvas."""

    MIME_TYPE = "application/x-ee-component"
    MINIMUM_VISIBLE_ROWS = 4

    def __init__(self, parent=None):
        """Create a drag-only list owned by an optional parent widget."""
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragOnly)

    def startDrag(self, _supported_actions):
        """Encode the selected ComponentType into a canvas drag payload.

        Args:
            _supported_actions: Qt-supplied action mask; this list always uses
                CopyAction, so the incoming value is intentionally unused.
        """
        item = self.currentItem()
        if item is None:
            return

        comp_type = item.data(Qt.UserRole)
        if comp_type is None:
            return

        mime_data = QMimeData()
        mime_data.setData(self.MIME_TYPE, comp_type.name.encode("utf-8"))
        mime_data.setText(comp_type.value)

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec_(Qt.CopyAction)

    def lock_minimum_visible_rows(self, row_count=None):
        """Reserve enough height to show the requested number of choices."""
        requested_rows = row_count or self.MINIMUM_VISIBLE_ROWS
        visible_rows = min(requested_rows, self.count())
        rows_height = sum(
            max(self.sizeHintForRow(row), self.fontMetrics().height() + 16)
            for row in range(visible_rows)
        )
        self.setMinimumHeight(rows_height + (2 * self.frameWidth()) + 2)

class MainWindow(QMainWindow):
    """Own and coordinate the application's visible circuit-editing workflow."""

    VALUE_FIELD_CONFIG = {
        ComponentType.RESISTOR: ("Resistance", "Ohm (\u03a9)", "e.g. 10"),
        ComponentType.CAPACITOR: ("Capacitance", "Farad (F)", "e.g. 0.000001"),
        ComponentType.INDUCTOR: ("Inductance", "Henry (H)", "e.g. 0.01"),
        ComponentType.VOLTAGE_SOURCE: ("Voltage", "Volt (V)", "e.g. 12"),
        ComponentType.CURRENT_SOURCE: ("Current", "Ampere (A)", "e.g. 0.5"),
    }
    COMPONENT_PREFIX = {
        ComponentType.RESISTOR: "R",
        ComponentType.CAPACITOR: "C",
        ComponentType.INDUCTOR: "L",
        ComponentType.VOLTAGE_SOURCE: "V",
        ComponentType.CURRENT_SOURCE: "I",
        ComponentType.NODE: "N",
    }
    VALUE_CATEGORY_TITLES = {
        ComponentType.RESISTOR: "Resistors",
        ComponentType.CAPACITOR: "Capacitors",
        ComponentType.INDUCTOR: "Inductors",
        ComponentType.VOLTAGE_SOURCE: "Voltage Sources",
        ComponentType.CURRENT_SOURCE: "Current Sources",
    }
    HELP_TEXT = (
        "Left-click: Place/Move\n"
        "Click + drag from Components to canvas\n"
        "Undo: Ctrl+Z or Undo button\n"
        "Mouse wheel: Zoom in/out\n"
        "Middle-click + drag: Pan view\n"
        "Right-click: Connect\n"
        "R key: Rotate\n"
        "Full screen: F11 or Full Screen button\n"
        "Escape: Exit full screen\n"
        "Assign values on right panel"
    )
    LEFT_PANEL_RATIO = 0.18
    RIGHT_PANEL_RATIO = 0.24
    
    def __init__(self):
        """Construct panels, connect signals, and restore saved UI settings."""
        super().__init__()
        self.setWindowTitle("Electrical Engineering Learning App")
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(0)
        
        # Center: Canvas (create first)
        self.canvas = CircuitCanvas(self)
        app = QApplication.instance()
        if app is not None:
            self.canvas.apply_theme(app.property("resolvedTheme"))
        self.canvas.component_added.connect(self.on_component_added)
        self.canvas.component_removed.connect(self.on_component_removed)
        self.canvas.canvas_cleared.connect(self.on_canvas_cleared)
        self.canvas.circuit_changed.connect(self.refresh_missing_value_hints)
        self.component_value_widgets = {}
        self._ai_request_in_progress = False
        self._ai_thread = None
        self._ai_worker = None
        self._ai_loading_dialog = None
        self._active_ai_prompt = ""
        self._active_analysis_request = None
        self._ignore_ai_response = False
        self.component_type_counters = {
            comp_type: 0 for comp_type in ComponentFactory.get_available_components()
        }
        
        # Left panel: Component palette
        self.create_component_panel()
        left_panel = self.component_panel
        self.create_value_panel()
        right_panel = self.value_panel

        # Layout: region proportions are managed programmatically and locked.
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(left_panel)
        self.main_splitter.addWidget(self.canvas)
        self.main_splitter.addWidget(right_panel)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([280, 820, 360])
        self.main_splitter.setHandleWidth(1)
        self._lock_splitter_handles()
        main_layout.addWidget(self.main_splitter, 1)
        
        main_widget.setLayout(main_layout)
        self.refresh_missing_value_hints()
        self.apply_resolution_preset(ResolutionManager.load_selected_resolution())
        QTimer.singleShot(300, self._check_ai_availability_on_first_launch)

    def _lock_splitter_handles(self):
        """Keep the three primary regions at their layout-defined proportions."""
        for handle_index in range(1, self.main_splitter.count()):
            handle = self.main_splitter.handle(handle_index)
            if handle is not None:
                handle.setEnabled(False)

    def _release_main_region_widths(self):
        """Release prior fixed panel widths before applying a new window size."""
        for panel in (self.component_panel, self.value_panel):
            panel.setMinimumWidth(0)
            panel.setMaximumWidth(16777215)

    def _apply_main_region_proportions(self):
        """Lock left, canvas, and right regions to stable width proportions."""
        if not hasattr(self, "main_splitter"):
            return
        content_width = max(self.width() - 12, 1)
        left_width = max(round(content_width * self.LEFT_PANEL_RATIO), 1)
        right_width = max(round(content_width * self.RIGHT_PANEL_RATIO), 1)
        center_width = max(content_width - left_width - right_width, 1)
        self.component_panel.setFixedWidth(left_width)
        self.value_panel.setFixedWidth(right_width)
        self.main_splitter.setSizes([left_width, center_width, right_width])
        self._lock_splitter_handles()

    def _apply_vertical_layout_profile(self):
        """Use a compact, non-overlapping sidebar profile on short windows."""
        if not hasattr(self, "component_panel_layout"):
            return
        compact = self.height() < 850
        self.component_list.lock_minimum_visible_rows(3 if compact else 4)
        margin = 8 if compact else 12
        self.component_panel_layout.setContentsMargins(margin, margin, margin, margin)
        self.component_panel_layout.setSpacing(5 if compact else 8)
        self.comment_browser.setMinimumHeight(60 if compact else 90)
        self.component_panel_content.updateGeometry()

    def apply_resolution_preset(self, key):
        """Resize to a preset while retaining safe manual resizing."""
        if self.isFullScreen():
            self.showNormal()
        self._release_main_region_widths()
        applied_key = ResolutionManager.apply_to_window(self, key)
        self._windowed_resolution_key = applied_key or key
        self._apply_main_region_proportions()
        self._apply_vertical_layout_profile()
        if hasattr(self, "full_screen_btn"):
            self.full_screen_btn.setText("Full Screen (F11)")
        return applied_key

    def enter_full_screen(self):
        """Use the current display while keeping all main regions proportional."""
        if self.isFullScreen():
            return
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.showFullScreen()
        self.full_screen_btn.setText("Exit Full Screen (F11)")
        QTimer.singleShot(0, self._apply_main_region_proportions)

    def exit_full_screen(self):
        """Return to the resolution selected in General settings."""
        if not self.isFullScreen():
            return
        self.showNormal()
        self.full_screen_btn.setText("Full Screen (F11)")
        resolution_key = getattr(
            self, "_windowed_resolution_key", ResolutionManager.load_selected_resolution()
        )
        QTimer.singleShot(0, lambda: self.apply_resolution_preset(resolution_key))

    def toggle_full_screen(self):
        """Switch between full-screen and the selected windowed preset."""
        if self.isFullScreen():
            self.exit_full_screen()
        else:
            self.enter_full_screen()
    
    def create_component_panel(self):
        """Create the component selection panel"""
        panel = QWidget()
        panel.setProperty("role", "sidePanel")
        layout = QVBoxLayout()
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # Title
        title = QLabel("Components")
        title.setProperty("role", "panelTitle")
        layout.addWidget(title)
        
        # Component list
        self.component_list = ComponentListWidget()
        self.component_list.setMinimumWidth(210)
        self.component_list.itemClicked.connect(self.on_component_selected)
        
        for comp_type in ComponentFactory.get_available_components():
            item = QListWidgetItem(comp_type.value)
            item.setData(Qt.UserRole, comp_type)
            self.component_list.addItem(item)

        self.component_list.lock_minimum_visible_rows()
        
        layout.addWidget(self.component_list)
        
        help_btn = QPushButton("Help")
        help_btn.setProperty("role", "sidebarAction")
        help_btn.clicked.connect(self.show_help_dialog)
        layout.addWidget(help_btn)

        export_btn = QPushButton("Export")
        export_btn.setProperty("role", "sidebarAction")
        export_btn.clicked.connect(self.export_circuit)
        layout.addWidget(export_btn)

        import_btn = QPushButton("Import")
        import_btn.setProperty("role", "sidebarAction")
        import_btn.clicked.connect(self.import_circuit)
        layout.addWidget(import_btn)

        self.solve_btn = QPushButton("Solve Circuit")
        self.solve_btn.setProperty("role", "primaryAction")
        self.solve_btn.clicked.connect(self.ask_ai_to_solve)
        layout.addWidget(self.solve_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.setProperty("role", "sidebarAction")
        settings_btn.clicked.connect(self.open_settings)
        layout.addWidget(settings_btn)

        self.full_screen_btn = QPushButton("Full Screen (F11)")
        self.full_screen_btn.setProperty("role", "sidebarAction")
        self.full_screen_btn.clicked.connect(self.toggle_full_screen)
        layout.addWidget(self.full_screen_btn)

        hint_title = QLabel("Circuit Comments")
        hint_title.setProperty("role", "sectionTitle")
        layout.addWidget(hint_title)

        self.comment_browser = QTextBrowser()
        self.comment_browser.setReadOnly(True)
        self.comment_browser.setOpenExternalLinks(False)
        self.comment_browser.setProperty("role", "commentBrowser")
        self.comment_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.comment_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Compact-height layouts reduce this safely; the outer sidebar scrolls
        # when all controls still cannot fit without overlap.
        self.comment_browser.setMinimumHeight(90)
        self.comment_browser.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.comment_browser.verticalScrollBar().setSingleStep(8)
        self.comment_browser.verticalScrollBar().setPageStep(80)
        layout.addWidget(self.comment_browser)
        
        layout.addStretch()

        undo_btn = QPushButton("Undo (Ctrl+Z)")
        undo_btn.clicked.connect(self.canvas.undo_last_action)
        layout.addWidget(undo_btn)

        center_btn = QPushButton("Back to Center View")
        center_btn.clicked.connect(self.canvas.back_to_center_view)
        layout.addWidget(center_btn)

        # Keep clear action at the bottom-left to reduce accidental clicks
        clear_btn = QPushButton("Clear Canvas")
        clear_btn.clicked.connect(self.canvas.clear_all)
        layout.addWidget(clear_btn)

        panel.setLayout(layout)
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        panel_scroll = QScrollArea()
        panel_scroll.setProperty("role", "sidePanel")
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setFrameShape(QFrame.NoFrame)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        panel_scroll.setWidget(panel)
        panel_scroll.setMinimumWidth(230)
        panel_scroll.setMaximumWidth(360)
        panel_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self.component_panel_layout = layout
        self.component_panel_content = panel
        self.component_panel = panel_scroll

    def create_value_panel(self):
        """Create right-side panel for per-component value assignment."""
        panel = QWidget()
        panel.setProperty("role", "valuePanel")
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Component Values")
        title.setProperty("role", "panelTitle")
        layout.addWidget(title)

        self.value_hint_label = QLabel("Place a value-based component to create a value box.")
        self.value_hint_label.setWordWrap(True)
        self.value_hint_label.setProperty("role", "mutedText")
        layout.addWidget(self.value_hint_label)

        self.value_scroll_area = QScrollArea()
        self.value_scroll_area.setWidgetResizable(True)
        self.value_scroll_area.setFrameShape(QFrame.NoFrame)
        self.value_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.value_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.value_list_container = QWidget()
        self.value_list_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.value_list_layout = QVBoxLayout()
        self.value_list_layout.setContentsMargins(0, 0, 0, 0)
        self.value_list_layout.setSpacing(8)
        self.value_list_layout.setAlignment(Qt.AlignTop)
        self.value_list_container.setLayout(self.value_list_layout)

        self.value_category_sections = {}
        for comp_type in ComponentFactory.get_available_components():
            if comp_type not in self.VALUE_FIELD_CONFIG:
                continue

            section_widget = QWidget()
            section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            section_layout = QVBoxLayout()
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(4)

            category_btn = QPushButton(self.VALUE_CATEGORY_TITLES.get(comp_type, f"{comp_type.value}s"))
            category_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            category_btn.setCheckable(True)
            category_btn.setChecked(True)
            category_btn.setProperty("role", "categoryHeader")
            category_btn.toggled.connect(
                lambda checked, category_type=comp_type: self.toggle_value_category(category_type, checked)
            )
            section_layout.addWidget(category_btn)

            category_content = QWidget()
            category_content_layout = QVBoxLayout()
            category_content_layout.setContentsMargins(8, 0, 0, 8)
            category_content_layout.setSpacing(6)
            category_content_layout.setAlignment(Qt.AlignTop)
            category_content.setLayout(category_content_layout)
            category_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            section_layout.addWidget(category_content)

            section_widget.setLayout(section_layout)
            self.value_list_layout.addWidget(section_widget)

            self.value_category_sections[comp_type] = {
                "button": category_btn,
                "content": category_content,
                "layout": category_content_layout,
            }

        self.value_scroll_area.setWidget(self.value_list_container)
        layout.addWidget(self.value_scroll_area, 1)

        panel.setLayout(layout)
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(560)
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.value_panel = panel

    def toggle_value_category(self, comp_type, expanded):
        """Expand/collapse one value category section."""
        section = self.value_category_sections.get(comp_type)
        if section is None:
            return
        section["content"].setVisible(expanded)
    
    def on_component_selected(self, item):
        """Handle component selection from list"""
        comp_type = item.data(Qt.UserRole)
        self.canvas.set_selected_component(comp_type)

    def on_component_added(self, component):
        """Create a value editor box when a new component is placed."""
        comp_type = component.comp_type
        self.component_type_counters[comp_type] += 1
        component_index = self.component_type_counters[comp_type]
        prefix = self.COMPONENT_PREFIX.get(comp_type, comp_type.value[:1].upper())
        component.reference_name = f"{prefix}#{component_index}"
        component.display_name = f"{comp_type.value} #{component_index}"
        if hasattr(component, "update_label_text"):
            component.update_label_text(component.reference_name)

        if comp_type == ComponentType.NODE:
            node_name = f"Node {self._node_alpha_label(component_index)}"
            component.reference_name = node_name
            component.display_name = node_name
            if hasattr(component, "update_label_text"):
                component.update_label_text(component.reference_name)
            component.assigned_value = ""
            component.value_unit = ""
            if not self.component_value_widgets:
                self.value_hint_label.setText("Node components do not require values.")
            self.refresh_missing_value_hints()
            return

        field_name, unit_label, placeholder = self.VALUE_FIELD_CONFIG.get(
            comp_type, ("Value", "Unit", "e.g. 1")
        )

        value_box = QFrame()
        value_box.setFrameShape(QFrame.StyledPanel)
        value_box.setProperty("role", "propertyCard")
        value_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        value_box_layout = QVBoxLayout()
        value_box_layout.setContentsMargins(10, 10, 10, 10)
        value_box_layout.setSpacing(6)

        title = QLabel(component.display_name)
        title.setProperty("role", "sectionTitle")
        value_box_layout.addWidget(title)

        ref_label = QLabel(f"Ref: {component.reference_name}")
        ref_label.setProperty("role", "mutedText")
        value_box_layout.addWidget(ref_label)

        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        value_input = QLineEdit()
        value_input.setMinimumWidth(120)
        value_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        value_input.setPlaceholderText(placeholder)
        value_input.textChanged.connect(
            lambda text, comp=component: self.on_component_value_changed(comp, text)
        )
        field_label = QLabel(f"{field_name}:")
        field_label.setProperty("role", "sectionTitle")
        form_layout.addRow(field_label, value_input)

        unit_title = QLabel("Unit:")
        unit_title.setProperty("role", "sectionTitle")
        unit_combo = self._create_unit_combo(component, comp_type, unit_label)
        form_layout.addRow(unit_title, unit_combo)
        value_box_layout.addLayout(form_layout)

        value_box.setLayout(value_box_layout)

        category_section = self.value_category_sections.get(comp_type)
        if category_section is not None:
            category_section["button"].setChecked(True)
            category_section["layout"].addWidget(value_box, 0, Qt.AlignTop)
        self.component_value_widgets[component] = (value_box, comp_type)
        self.value_hint_label.setText("Edit each component value below.")
        component.assigned_value = ""
        self.refresh_missing_value_hints()

    def on_component_removed(self, component):
        """Remove value editor when a component is deleted."""
        value_entry = self.component_value_widgets.pop(component, None)
        if value_entry is None:
            if not self.component_value_widgets:
                self.value_hint_label.setText("Place a value-based component to create a value box.")
            self.refresh_missing_value_hints()
            return

        value_box, comp_type = value_entry
        category_section = self.value_category_sections.get(comp_type)
        if category_section is not None:
            category_section["layout"].removeWidget(value_box)

        value_box.deleteLater()

        if not self.component_value_widgets:
            self.value_hint_label.setText("Place a value-based component to create a value box.")
        self.refresh_missing_value_hints()

    def on_canvas_cleared(self):
        """Reset value assignment panel when canvas is cleared."""
        for value_box, comp_type in list(self.component_value_widgets.values()):
            category_section = self.value_category_sections.get(comp_type)
            if category_section is not None:
                category_section["layout"].removeWidget(value_box)
            value_box.deleteLater()

        self.component_value_widgets.clear()
        self.component_type_counters = {
            comp_type: 0 for comp_type in ComponentFactory.get_available_components()
        }
        self.value_hint_label.setText("Place a value-based component to create a value box.")
        self.refresh_missing_value_hints()

    def on_component_value_changed(self, component, value_text):
        """Persist the typed value on the component instance."""
        component.assigned_value = value_text.strip()
        self.refresh_missing_value_hints()

    def on_component_unit_changed(self, component, unit_symbol):
        """Persist the selected engineering unit scale on the component."""
        component.value_unit = normalize_unit_symbol(component.comp_type, unit_symbol)
        self.refresh_missing_value_hints()

    def _create_unit_combo(self, component, comp_type, legacy_default=""):
        """Create a unit-scale selector and initialize the component's unit."""
        unit_combo = QComboBox()
        unit_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for option in options_for_component(comp_type):
            unit_combo.addItem(option.label, option.symbol)

        current_symbol = normalize_unit_symbol(
            comp_type, getattr(component, "value_unit", legacy_default)
        )
        current_index = unit_combo.findData(current_symbol)
        if current_index >= 0:
            unit_combo.setCurrentIndex(current_index)
        component.value_unit = current_symbol
        unit_combo.currentIndexChanged.connect(
            lambda _index, comp=component, combo=unit_combo: self.on_component_unit_changed(
                comp, combo.currentData()
            )
        )
        return unit_combo

    def show_help_dialog(self):
        """Show usage instructions in a help dialog."""
        QMessageBox.information(self, "Help", self.HELP_TEXT)

    def _check_ai_availability_on_first_launch(self):
        """
        On the very first run, the default AI provider is Ollama Local.
        Quietly check whether it's reachable so we can point new users at
        Settings up front instead of failing silently later.
        """
        if not is_first_launch():
            return
        mark_first_launch_seen()

        settings = load_settings()
        if settings.get("provider") != "ollama":
            return

        try:
            provider = create_provider(
                "ollama", model=settings.get("model", ""), endpoint=settings.get("endpoint", "")
            )
            success, _message = provider.test_connection()
        except Exception:  # noqa: BLE001 - never let a startup check crash the app
            success = False

        if success:
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Local AI Unavailable")
        box.setText(
            "Local AI unavailable.\n\nInstall/start Ollama or choose another AI provider."
        )
        settings_btn = box.addButton("Open Settings", QMessageBox.ActionRole)
        box.addButton("Dismiss", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() == settings_btn:
            self.open_settings()

    def open_settings(self):
        """Open the application settings dialog."""
        SettingsDialog(self).exec_()

    def open_ai_settings(self):
        """Compatibility wrapper for older callers."""
        self.open_settings()

    def ask_ai_to_solve(self):
        """
        Validate the circuit, translate it into an AI-ready description, and
        either send it to the configured AI provider or fall back to a
        manual copy-paste prompt. The AI response is only ever displayed;
        it is never written back into the circuit model.
        """
        if self._ai_request_in_progress:
            return

        if not self.canvas.components:
            QMessageBox.warning(self, "No Circuit", "Please add components to the canvas before requesting AI analysis.")
            return

        value_component_types = set(self.VALUE_FIELD_CONFIG.keys())
        value_components = [
            component for component in self.canvas.components
            if is_value_component(component, value_component_types)
        ]
        if not value_components:
            QMessageBox.warning(
                self, "No Circuit",
                "Add value-bearing components (resistors, sources, etc.) before requesting AI analysis.",
            )
            return

        uf = build_nets(self.canvas.components, self.canvas.connection_lines)
        wiring_issues = run_wiring_checks(
            self.canvas.components, value_components, value_component_types, self.component_reference, uf
        )
        if wiring_issues:
            QMessageBox.warning(self, "Fix Circuit Wiring First", "\n".join(wiring_issues))
            return

        analysis_dialog = AnalysisDialog(value_components, self.component_reference, self)
        if analysis_dialog.exec_() != QDialog.Accepted or analysis_dialog.result_request is None:
            return
        analysis_request = analysis_dialog.result_request

        circuit_text = generate_circuit_export(
            self.canvas.components, value_component_types, self.component_reference, self.canvas.connection_lines,
            target_ref=(
                analysis_request.target_component
                if analysis_request.mode == AnalysisMode.SOLVE_MISSING_VALUE
                else None
            ),
        )
        prompt = build_ai_prompt(circuit_text, analysis_request)

        settings = load_settings()
        if not is_configured(settings):
            ManualPromptDialog(prompt, self).exec_()
            return

        self._start_ai_request(settings, prompt, analysis_request)

    def _start_ai_request(self, settings, prompt, analysis_request):
        """Start the provider request on a worker thread."""
        self._ignore_ai_response = False
        self._active_ai_prompt = prompt
        self._active_analysis_request = analysis_request
        provider = create_provider(
            settings["provider"],
            api_key=settings["api_key"],
            model=settings["model"],
            endpoint=settings["endpoint"],
        )
        self._set_ai_busy(True)

        self._ai_loading_dialog = AILoadingDialog(self)
        self._ai_loading_dialog.show()

        self._ai_thread = QThread(self)
        self._ai_worker = AIRequestWorker(provider, prompt, timeout=300)
        self._ai_worker.moveToThread(self._ai_thread)
        self._ai_thread.started.connect(self._ai_worker.run)
        self._ai_worker.finished.connect(self._on_ai_response_ready)
        self._ai_worker.failed.connect(self._on_ai_request_failed)
        self._ai_worker.finished.connect(self._ai_thread.quit)
        self._ai_worker.failed.connect(self._ai_thread.quit)
        self._ai_thread.finished.connect(self._ai_worker.deleteLater)
        self._ai_thread.finished.connect(self._ai_thread.deleteLater)
        self._ai_thread.finished.connect(self._clear_ai_request_references)
        self._ai_thread.start()

    def _on_ai_response_ready(self, response_text):
        """Handle a successful provider return on the UI thread."""
        if self._ignore_ai_response:
            return

        self._close_ai_loading_dialog()
        self._set_ai_busy(False)

        solution_text, explanation_text = split_solution_and_explanation(response_text)
        show_explanation = not (
            self._active_analysis_request is not None
            and self._active_analysis_request.mode == AnalysisMode.FULL_ANALYSIS
        )
        ResultDialog(
            solution_text,
            explanation_text,
            self,
            show_explanation=show_explanation,
        ).exec_()

    def _on_ai_request_failed(self, message):
        """Handle provider failure or timeout and transition to manual mode."""
        active_prompt = self._active_ai_prompt
        self._close_ai_loading_dialog()
        self._set_ai_busy(False)
        QMessageBox.warning(
            self,
            "AI Request Failed",
            "Could not get a response from the AI provider:\n\n"
            f"{message}\n\n"
            "Falling back to manual mode.",
        )
        if active_prompt:
            ManualPromptDialog(active_prompt, self).exec_()

    def _set_ai_busy(self, busy):
        """Lock or unlock circuit editing while an AI request is active."""
        self._ai_request_in_progress = busy
        if hasattr(self, "main_splitter"):
            self.main_splitter.setEnabled(not busy)
            if not busy:
                self._lock_splitter_handles()
        if hasattr(self, "solve_btn"):
            self.solve_btn.setEnabled(not busy)

    def _close_ai_loading_dialog(self):
        """Stop and release the modeless loading dialog when one exists."""
        if self._ai_loading_dialog is not None:
            self._ai_loading_dialog.stop()
            self._ai_loading_dialog.deleteLater()
            self._ai_loading_dialog = None

    def _clear_ai_request_references(self):
        """Release worker objects and restore editing after a request ends."""
        self._ai_thread = None
        self._ai_worker = None
        self._ai_loading_dialog = None
        self._active_ai_prompt = None
        self._active_analysis_request = None
        if self._ai_request_in_progress:
            self._set_ai_busy(False)

    def _cleanup_ai_thread(self):
        """Handle QThread completion by clearing request-owned references."""
        self._clear_ai_request_references()

    def _refresh_value_widgets_from_components(self):
        """Sync each value box's text field with its component's current assigned_value."""
        for component, (value_box, _comp_type) in self.component_value_widgets.items():
            value_input = value_box.findChild(QLineEdit)
            if value_input is not None:
                current_value = getattr(component, "assigned_value", "")
                if value_input.text() != current_value:
                    value_input.blockSignals(True)
                    value_input.setText(current_value)
                    value_input.blockSignals(False)
        self.refresh_missing_value_hints()

    def export_circuit(self):
        """Export the current circuit to a JSON file."""
        if not self.canvas.components:
            QMessageBox.warning(self, "No Circuit", "Please add components to the canvas before exporting.")
            return

        exports_dir = resource_path("Circuit_exports")
        os.makedirs(exports_dir, exist_ok=True)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Circuit",
            exports_dir,
            "Circuit Files (*.circuit);;JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            circuit_name = "Untitled Circuit"
            if file_path.endswith(".circuit") or file_path.endswith(".json"):
                circuit_name = file_path.split("/")[-1].split(".")[0]

            circuit_dict = serialize_circuit(
                self.canvas.components, 
                circuit_name,
                self.canvas.connection_lines
            )
            json_str = serialize_to_json(circuit_dict)

            with open(file_path, "w") as f:
                f.write(json_str)

            QMessageBox.information(self, "Success", f"Circuit exported to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export circuit: {str(e)}")

    def import_circuit(self):
        """Import a circuit from a JSON file."""
        exports_dir = resource_path("Circuit_exports")

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Circuit",
            exports_dir,
            "Circuit Files (*.circuit);;JSON Files (*.json);;All Files (*)"
        )

        if not file_path:
            return

        try:
            with open(file_path, "r") as f:
                json_str = f.read()

            circuit_dict = deserialize_from_json(json_str)

            # Clear canvas first
            self.canvas.clear_all()

            # Reconstruct circuit
            ref_to_component = reconstruct_circuit_from_dict(circuit_dict, self.canvas)

            # Update counters and populate value fields from loaded components
            for comp_id, component in ref_to_component.items():
                if component.comp_type in self.VALUE_FIELD_CONFIG:
                    # Extract number from reference like "R#1" to set counter correctly
                    ref_name = component.reference_name
                    if "#" in ref_name:
                        try:
                            num = int(ref_name.split("#")[1])
                            current_count = self.component_type_counters.get(component.comp_type, 0)
                            if num > current_count:
                                self.component_type_counters[component.comp_type] = num
                        except (ValueError, IndexError):
                            pass

                    # Create value widget for this component
                    self._create_value_widget_for_component(component)
                elif component.comp_type == ComponentType.NODE:
                    # Extract the letter suffix from a name like "Node C" so
                    # newly placed nodes continue the alphabet instead of
                    # colliding with an imported node's name.
                    letters = (component.reference_name or "").replace("Node", "").strip()
                    num = self._node_alpha_index(letters)
                    if num > self.component_type_counters.get(ComponentType.NODE, 0):
                        self.component_type_counters[ComponentType.NODE] = num

            app = QApplication.instance()
            if app is not None:
                self.canvas.apply_theme(app.property("resolvedTheme"))

            self.canvas.circuit_changed.emit()
            QMessageBox.information(self, "Success", f"Circuit imported from {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import circuit: {str(e)}")

    def _create_value_widget_for_component(self, component):
        """Create a value widget for a component without triggering on_component_added."""
        comp_type = component.comp_type

        if comp_type == ComponentType.NODE:
            component.assigned_value = ""
            component.value_unit = ""
            if not self.component_value_widgets:
                self.value_hint_label.setText("Node components do not require values.")
            self.refresh_missing_value_hints()
            return

        field_name, unit_label, placeholder = self.VALUE_FIELD_CONFIG.get(
            comp_type, ("Value", "Unit", "e.g. 1")
        )

        value_box = QFrame()
        value_box.setFrameShape(QFrame.StyledPanel)
        value_box.setProperty("role", "propertyCard")
        value_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        value_box_layout = QVBoxLayout()
        value_box_layout.setContentsMargins(10, 10, 10, 10)
        value_box_layout.setSpacing(6)

        title = QLabel(component.display_name)
        title.setProperty("role", "sectionTitle")
        value_box_layout.addWidget(title)

        ref_label = QLabel(f"Ref: {component.reference_name}")
        ref_label.setProperty("role", "mutedText")
        value_box_layout.addWidget(ref_label)

        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        value_input = QLineEdit()
        value_input.setMinimumWidth(120)
        value_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        value_input.setPlaceholderText(placeholder)
        value_input.setText(getattr(component, "assigned_value", ""))
        value_input.textChanged.connect(
            lambda text, comp=component: self.on_component_value_changed(comp, text)
        )
        field_label = QLabel(f"{field_name}:")
        field_label.setProperty("role", "sectionTitle")
        form_layout.addRow(field_label, value_input)

        unit_title = QLabel("Unit:")
        unit_title.setProperty("role", "sectionTitle")
        unit_combo = self._create_unit_combo(component, comp_type, unit_label)
        form_layout.addRow(unit_title, unit_combo)
        value_box_layout.addLayout(form_layout)

        value_box.setLayout(value_box_layout)

        category_section = self.value_category_sections.get(comp_type)
        if category_section is not None:
            category_section["button"].setChecked(True)
            category_section["layout"].addWidget(value_box, 0, Qt.AlignTop)
        self.component_value_widgets[component] = (value_box, comp_type)
        self.value_hint_label.setText("Edit each component value below.")
        self.refresh_missing_value_hints()

    def component_reference(self, component):
        """Return display reference for a component."""
        return getattr(component, "reference_name", component.comp_type.value)

    @staticmethod
    def _node_alpha_label(index):
        """1 -> 'A', 2 -> 'B', ..., 26 -> 'Z', 27 -> 'AA', 28 -> 'AB', ..."""
        label = ""
        n = index
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            label = chr(65 + remainder) + label
        return label

    @staticmethod
    def _node_alpha_index(label):
        """Inverse of _node_alpha_label: 'A' -> 1, 'B' -> 2, ..., 'AA' -> 27, ..."""
        index = 0
        for char in label:
            if not char.isalpha():
                return 0
            index = index * 26 + (ord(char.upper()) - 64)
        return index

    def highlighted_reference_html(self, reference):
        """Return a boxed/highlighted HTML snippet for a component reference."""
        return (
            "<span style='background-color:#fff59d; border:1px solid #c7b200; "
            "color:#1f2933; padding:1px 4px; border-radius:3px; font-weight:bold;'>"
            f"{reference}</span>"
        )

    def set_comment_messages(self, messages):
        """Render read-only rich comment messages with smooth scrolling."""
        html_messages = []
        for message in messages:
            safe_message = self._comment_message_to_html(message)
            html_messages.append(f"<p>{safe_message}</p>")
        self.comment_browser.setHtml(
            "<html><body>" + "\n".join(html_messages) + "</body></html>"
        )
        scrollbar = self.comment_browser.verticalScrollBar()
        scrollbar.setSingleStep(8)
        scrollbar.setPageStep(80)

    @staticmethod
    def _comment_message_to_html(message):
        """Preserve known rich highlight spans while escaping plain messages."""
        marker = "<span"
        if marker in message:
            prefix, marker_and_after = message.split(marker, 1)
            span_markup = marker + marker_and_after
            return escape(prefix) + span_markup
        return escape(message)

    def refresh_missing_value_hints(self):
        """Show left-panel comments for missing values and circuit logic checks."""
        missing_components = []
        for component in self.canvas.components:
            if component.comp_type not in self.VALUE_FIELD_CONFIG:
                continue
            if not getattr(component, "assigned_value", "").strip():
                missing_components.append(component)

        comments = []
        if missing_components:
            target_component = missing_components[0]
            target_name = self.component_reference(target_component)
            boxed_name = self.highlighted_reference_html(target_name)
            remaining_count = len(missing_components) - 1
            if remaining_count == 0:
                comments.append(f"Solving circuit for {boxed_name}?")
            else:
                comments.append(
                    f"Solving circuit for {boxed_name}? "
                    f"({remaining_count} more component value(s) missing)"
                )
        else:
            comments.append("All component values are entered.")

        comments.extend(
            analyze_circuit(
                self.canvas.components,
                set(self.VALUE_FIELD_CONFIG.keys()),
                self.component_reference,
                self.canvas.connection_lines,
            )
        )
        self.set_comment_messages(comments)

    def keyPressEvent(self, event):
        """Handle window-level keyboard shortcuts"""
        if event.key() == Qt.Key_F11:
            self.toggle_full_screen()
            event.accept()
            return

        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self.exit_full_screen()
            event.accept()
            return

        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.canvas.selected_component:
            self.canvas.delete_selected_component()
            event.accept()
            return

        super().keyPressEvent(event)

    def resizeEvent(self, event):
        """Maintain locked main-region proportions during full-screen transitions."""
        super().resizeEvent(event)
        if hasattr(self, "main_splitter"):
            self._apply_main_region_proportions()
            self._apply_vertical_layout_profile()

    def closeEvent(self, event):
        """Avoid tearing down the window while an AI worker thread is active."""
        if self._ai_request_in_progress:
            event.ignore()
            return
        super().closeEvent(event)
