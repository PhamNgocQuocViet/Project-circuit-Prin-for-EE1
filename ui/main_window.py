"""Coordinate the application's main window and its top-level workflows.

Version 1.4 keeps the prototype's circuit/AI/import-export logic while using a
canvas-first interface: one top toolbar, overlay drawers for components and
values, live circuit comments, and a persistent light/dark quick toggle.
"""

import os
from html import escape

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QLabel, QComboBox, QLineEdit, QFormLayout, QScrollArea,
    QFrame, QSizePolicy, QMessageBox, QFileDialog, QApplication, QDialog,
    QTextBrowser, QTabWidget,
)
from PyQt5.QtCore import Qt, QMimeData, QThread, QTimer, QSize, QPointF, QRectF
from PyQt5.QtGui import QDrag, QIcon, QPixmap, QPainter, QPainterPath, QPen, QColor

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
from ui.theme_manager import ThemeManager, THEME_DARK, THEME_LIGHT
from ai_assistant.analysis_dialog import AnalysisDialog
from ai_assistant.analysis_request import AnalysisMode
from ai_assistant.result_dialog import ResultDialog, ManualPromptDialog, split_solution_and_explanation


class ComponentListWidget(QListWidget):
    """Drag-enabled component list used inside the Add Component drawer."""

    MIME_TYPE = "application/x-ee-component"
    MINIMUM_VISIBLE_ROWS = 4

    def __init__(self, parent=None):
        """Create a palette list that supports drag-only component placement."""
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragOnly)
        self.setIconSize(QSize(68, 30))
        self.setSpacing(2)

    def startDrag(self, _supported_actions):
        """Encode the selected component type into the canvas drag payload."""
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
        """Reserve enough height for a useful number of palette entries."""
        requested_rows = row_count or self.MINIMUM_VISIBLE_ROWS
        visible_rows = min(requested_rows, self.count())
        rows_height = sum(
            max(self.sizeHintForRow(row), self.fontMetrics().height() + 16)
            for row in range(visible_rows)
        )
        self.setMinimumHeight(rows_height + (2 * self.frameWidth()) + 2)


class MainWindow(QMainWindow):
    """Canvas-first circuit editor with non-destructive overlay drawers."""

    VALUE_FIELD_CONFIG = {
        ComponentType.RESISTOR: ("Resistance", "Ohm (Ω)", "e.g. 10"),
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
        "Add Component: open the left component drawer\n"
        "Left-click: place or move a component\n"
        "Drag from the component drawer onto the canvas\n"
        "Undo: Ctrl+Z or Undo\n"
        "Mouse wheel: zoom in/out\n"
        "Middle-click + drag: pan view\n"
        "Right-click: connect components\n"
        "R key: rotate selected component\n"
        "Delete/Backspace: delete selected component\n"
        "F11: full screen, Escape: exit full screen\n"
        "Values: open the right value drawer\n"
        "Circuit comments update automatically in the Add Component drawer"
    )
    COMPONENT_DRAWER_WIDTH = 330
    VALUE_DRAWER_WIDTH = 390

    def __init__(self):
        """Build the editor, connect workflows, and restore saved UI settings."""
        super().__init__()
        self.setWindowTitle("Electrical Engineering Learning App")

        # Main-window-owned state. Circuit geometry remains owned by the
        # canvas; this mapping only tracks the corresponding value editors.
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

        root = QWidget()
        self.setCentralWidget(root)
        self.main_layout = QVBoxLayout(root)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.canvas = CircuitCanvas(self)
        app = QApplication.instance()
        if app is not None:
            self.canvas.apply_theme(app.property("resolvedTheme"))
        self.canvas.component_added.connect(self.on_component_added)
        self.canvas.component_removed.connect(self.on_component_removed)
        self.canvas.canvas_cleared.connect(self.on_canvas_cleared)
        self.canvas.circuit_changed.connect(self.refresh_missing_value_hints)

        self.create_top_toolbar()
        self.main_layout.addWidget(self.top_toolbar)

        self.workspace = QFrame()
        self.workspace.setObjectName("workspace")
        workspace_layout = QVBoxLayout(self.workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self.canvas)
        self.main_layout.addWidget(self.workspace, 1)

        self.create_component_panel()
        self.create_value_panel()
        # Drawer widgets are children of the workspace so they float above the
        # canvas without consuming or resizing its drawing area.
        self.component_panel.setParent(self.workspace)
        self.value_panel.setParent(self.workspace)
        self.component_panel.hide()
        self.value_panel.hide()

        self.create_information_bar()
        self.main_layout.addWidget(self.information_bar)

        self.refresh_missing_value_hints()
        self.apply_resolution_preset(ResolutionManager.load_selected_resolution())
        self._position_overlay_drawers()
        if app is not None:
            self.apply_theme(app.property("resolvedTheme") or THEME_LIGHT)
        QTimer.singleShot(300, self._check_ai_availability_on_first_launch)

    # ------------------------------------------------------------------
    # Main layout
    # ------------------------------------------------------------------
    def create_top_toolbar(self):
        """Create the compact command bar for application-level actions."""
        self.top_toolbar = QFrame()
        self.top_toolbar.setObjectName("topToolbar")
        layout = QHBoxLayout(self.top_toolbar)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(6)

        def add_button(text, callback, role="toolbarButton", tooltip=""):
            """Add a consistently styled toolbar button and return it."""
            button = QPushButton(text)
            button.setProperty("role", role)
            if tooltip:
                button.setToolTip(tooltip)
            button.clicked.connect(callback)
            layout.addWidget(button)
            return button

        self.add_component_button = add_button("＋ Add Component", self.toggle_component_drawer, "primaryAction")
        self.import_btn = add_button("⌂ Open", self.import_circuit, tooltip="Open an editable circuit file")
        self.export_btn = add_button("▣ Save", self.export_circuit, tooltip="Save the current circuit")
        layout.addSpacing(6)
        self.undo_btn = add_button("↶ Undo", self.canvas.undo_last_action)
        self.delete_btn = add_button("⌫ Delete", self.delete_selected_component_from_toolbar)
        self.fit_btn = add_button("⌖ Fit View", self.canvas.back_to_center_view)
        self.values_btn = add_button("≡ Values", self.toggle_value_drawer)
        layout.addSpacing(6)
        self.solve_btn = add_button("✦ AI Solve", self.ask_ai_to_solve, "aiAction")
        self.help_btn = add_button("? Help", self.show_help_dialog)
        self.settings_btn = add_button("⚙ Settings", self.open_settings)
        self.full_screen_btn = add_button("⛶ Full Screen", self.toggle_full_screen)
        layout.addStretch(1)
        self.theme_btn = add_button("◐ Theme", self.toggle_theme, "themeToggle")
        self.clear_btn = add_button("Clear All", self.clear_canvas_from_toolbar, "dangerAction")

    def create_component_panel(self):
        """Create the left overlay containing categorized component choices."""
        panel = QFrame()
        panel.setProperty("role", "overlayDrawer")
        panel.setObjectName("componentDrawer")
        panel.setFixedWidth(self.COMPONENT_DRAWER_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Add Component")
        title.setProperty("role", "drawerTitle")
        close_btn = QPushButton("×")
        close_btn.setProperty("role", "drawerClose")
        close_btn.setFixedSize(32, 32)
        close_btn.clicked.connect(self.toggle_component_drawer)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(close_btn)
        layout.addLayout(header)

        subtitle = QLabel("Choose a symbol, then click the canvas to place it. You can also drag it onto the grid.")
        subtitle.setWordWrap(True)
        subtitle.setProperty("role", "mutedText")
        layout.addWidget(subtitle)

        self.component_tabs = QTabWidget()
        self.component_tabs.setObjectName("componentTabs")
        self.basic_component_list = ComponentListWidget()
        self.electronics_component_list = ComponentListWidget()
        self.automation_component_list = ComponentListWidget()
        self.component_lists = [
            self.basic_component_list,
            self.electronics_component_list,
            self.automation_component_list,
        ]
        self.component_tab_definitions = (
            ("Basic", self.basic_component_list),
            ("Electronics", self.electronics_component_list),
            ("Automation", self.automation_component_list),
        )
        for component_list in self.component_lists:
            component_list.itemClicked.connect(self.on_component_selected)

        self.component_list = self.basic_component_list  # compatibility alias
        layout.addWidget(self.component_tabs, 1)

        comments_title = QLabel("Circuit Comments")
        comments_title.setProperty("role", "sectionTitle")
        layout.addWidget(comments_title)

        self.comment_browser = QTextBrowser()
        self.comment_browser.setReadOnly(True)
        self.comment_browser.setOpenExternalLinks(False)
        self.comment_browser.setProperty("role", "commentBrowser")
        self.comment_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.comment_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.comment_browser.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.comment_browser.setMinimumHeight(105)
        self.comment_browser.setMaximumHeight(165)
        layout.addWidget(self.comment_browser)

        self.component_panel = panel
        self._populate_component_lists()

    def _populate_component_lists(self):
        """Rebuild categorized palette entries and hide empty categories."""
        for component_list in getattr(self, "component_lists", []):
            component_list.clear()

        for comp_type in ComponentFactory.get_available_components():
            item = QListWidgetItem(self._component_icon(comp_type), comp_type.value)
            item.setData(Qt.UserRole, comp_type)
            item.setSizeHint(QSize(0, 48))
            category = self._component_category(comp_type)
            target = {
                "electronics": self.electronics_component_list,
                "automation": self.automation_component_list,
            }.get(category, self.basic_component_list)
            target.addItem(item)

        self._sync_visible_component_tabs()

    def _sync_visible_component_tabs(self):
        """Show only category tabs backed by at least one real component."""
        current_list = self.component_tabs.currentWidget()
        while self.component_tabs.count():
            self.component_tabs.removeTab(0)

        for title, component_list in self.component_tab_definitions:
            if component_list.count() > 0:
                self.component_tabs.addTab(component_list, title)

        current_index = self.component_tabs.indexOf(current_list)
        if current_index >= 0:
            self.component_tabs.setCurrentIndex(current_index)
        self.component_tabs.setVisible(self.component_tabs.count() > 0)

    @staticmethod
    def _component_category(comp_type):
        """Infer the palette category from a component enum name and label."""
        name = f"{getattr(comp_type, 'name', '')} {getattr(comp_type, 'value', '')}".lower()
        if any(word in name for word in ("relay", "contactor", "motor", "plc", "push button", "sensor")):
            return "automation"
        if any(word in name for word in ("diode", "transistor", "op amp", "op-amp", "led")):
            return "electronics"
        return "basic"

    def _component_icon(self, comp_type):
        """Draw the same schematic language used on the canvas into a list icon."""
        pixmap = QPixmap(68, 30)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        app = QApplication.instance()
        dark = bool(app and app.property("resolvedTheme") == THEME_DARK)
        symbol = QColor(235, 240, 245) if dark else QColor(24, 27, 31)
        pen = QPen(symbol, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        y = 15.0
        left, right = 5.0, 63.0

        if comp_type == ComponentType.RESISTOR:
            path = QPainterPath(QPointF(left, y))
            path.lineTo(13, y)
            for point in ((18, 8), (23, 22), (28, 8), (33, 22), (38, 8), (43, 22), (48, y)):
                path.lineTo(*point)
            path.lineTo(right, y)
            painter.drawPath(path)
        elif comp_type == ComponentType.CAPACITOR:
            painter.drawLine(QPointF(left, y), QPointF(29, y))
            painter.drawLine(QPointF(29, 6), QPointF(29, 24))
            painter.drawLine(QPointF(38, 6), QPointF(38, 24))
            painter.drawLine(QPointF(38, y), QPointF(right, y))
        elif comp_type == ComponentType.INDUCTOR:
            path = QPainterPath(QPointF(left, y))
            path.lineTo(12, y)
            for x in (12, 23, 34, 45):
                path.cubicTo(x, 5, x + 10, 5, x + 10, y)
            path.lineTo(right, y)
            painter.drawPath(path)
        elif comp_type in (ComponentType.VOLTAGE_SOURCE, ComponentType.CURRENT_SOURCE):
            painter.drawLine(QPointF(left, y), QPointF(22, y))
            painter.drawEllipse(QPointF(34, y), 10, 10)
            painter.drawLine(QPointF(44, y), QPointF(right, y))
            if comp_type == ComponentType.VOLTAGE_SOURCE:
                painter.drawLine(QPointF(29, 11), QPointF(29, 17))
                painter.drawLine(QPointF(26, 14), QPointF(32, 14))
                painter.drawLine(QPointF(36, 16), QPointF(42, 16))
            else:
                painter.drawLine(QPointF(40, y), QPointF(28, y))
                painter.drawLine(QPointF(28, y), QPointF(33, 11))
                painter.drawLine(QPointF(28, y), QPointF(33, 19))
        elif comp_type == ComponentType.NODE:
            dot = QColor(87, 166, 255) if dark else QColor(14, 55, 102)
            painter.setPen(QPen(dot, 1))
            painter.setBrush(dot)
            painter.drawEllipse(QRectF(29, 10, 10, 10))

        painter.end()
        return QIcon(pixmap)

    def create_value_panel(self):
        """Create the right overlay used to edit per-component values."""
        panel = QFrame()
        panel.setProperty("role", "overlayDrawer")
        panel.setObjectName("valueDrawer")
        panel.setFixedWidth(self.VALUE_DRAWER_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Component Values")
        title.setProperty("role", "drawerTitle")
        close_btn = QPushButton("×")
        close_btn.setProperty("role", "drawerClose")
        close_btn.setFixedSize(32, 32)
        close_btn.clicked.connect(self.toggle_value_drawer)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(close_btn)
        layout.addLayout(header)

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
        self.value_list_layout = QVBoxLayout(self.value_list_container)
        self.value_list_layout.setContentsMargins(0, 0, 0, 0)
        self.value_list_layout.setSpacing(8)
        self.value_list_layout.setAlignment(Qt.AlignTop)

        self.value_category_sections = {}
        for comp_type in ComponentFactory.get_available_components():
            if comp_type not in self.VALUE_FIELD_CONFIG:
                continue
            section_widget = QWidget()
            section_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            section_layout = QVBoxLayout(section_widget)
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
            category_content_layout = QVBoxLayout(category_content)
            category_content_layout.setContentsMargins(8, 0, 0, 8)
            category_content_layout.setSpacing(6)
            category_content_layout.setAlignment(Qt.AlignTop)
            category_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            section_layout.addWidget(category_content)
            self.value_list_layout.addWidget(section_widget)
            self.value_category_sections[comp_type] = {
                "button": category_btn,
                "content": category_content,
                "layout": category_content_layout,
            }
        self.value_scroll_area.setWidget(self.value_list_container)
        layout.addWidget(self.value_scroll_area, 1)
        self.value_panel = panel

    def create_information_bar(self):
        """Create the persistent status and active-theme information bar."""
        self.information_bar = QFrame()
        self.information_bar.setProperty("role", "informationBar")
        self.information_bar.setFixedHeight(34)
        layout = QHBoxLayout(self.information_bar)
        layout.setContentsMargins(12, 0, 12, 0)
        self.status_label = QLabel('Ready — choose “Add Component” to begin')
        self.status_label.setProperty("role", "statusText")
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self.theme_status_label = QLabel("")
        self.theme_status_label.setProperty("role", "mutedText")
        layout.addWidget(self.theme_status_label)

    # ------------------------------------------------------------------
    # Drawers / toolbar actions
    # ------------------------------------------------------------------
    def _position_overlay_drawers(self):
        """Anchor both drawers to workspace edges after any resize."""
        if not hasattr(self, "workspace"):
            return
        height = max(0, self.workspace.height())
        if hasattr(self, "component_panel"):
            self.component_panel.setGeometry(0, 0, self.COMPONENT_DRAWER_WIDTH, height)
        if hasattr(self, "value_panel"):
            self.value_panel.setGeometry(
                max(0, self.workspace.width() - self.VALUE_DRAWER_WIDTH),
                0,
                self.VALUE_DRAWER_WIDTH,
                height,
            )

    def toggle_component_drawer(self):
        """Toggle the component drawer and close the competing value drawer."""
        should_show = not self.component_panel.isVisible()
        if should_show:
            self.value_panel.hide()
            self._position_overlay_drawers()
            self.component_panel.show()
            self.component_panel.raise_()
            self.status_label.setText("Choose a component symbol, then click the canvas to place it.")
        else:
            self.component_panel.hide()

    def toggle_value_drawer(self):
        """Toggle the value drawer and close the competing component drawer."""
        should_show = not self.value_panel.isVisible()
        if should_show:
            self.component_panel.hide()
            self._position_overlay_drawers()
            self.value_panel.show()
            self.value_panel.raise_()
            self.status_label.setText("Edit component values in the right drawer.")
        else:
            self.value_panel.hide()

    def delete_selected_component_from_toolbar(self):
        """Delete the active canvas component or report that none is selected."""
        if getattr(self.canvas, "selected_component", None) is None:
            self.status_label.setText("Select a component before deleting it.")
            return
        self.canvas.delete_selected_component()
        self.status_label.setText("Component deleted.")

    def clear_canvas_from_toolbar(self):
        """Clear all circuit data and publish a short status message."""
        self.canvas.clear_all()
        self.status_label.setText("Canvas cleared.")

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def toggle_theme(self):
        """Switch directly between concrete light and dark themes."""
        app = QApplication.instance()
        if app is None:
            return
        current = app.property("resolvedTheme") or THEME_LIGHT
        target = THEME_LIGHT if current == THEME_DARK else THEME_DARK
        ThemeManager.apply_theme(app=app, mode=target, persist=True)

    def apply_theme(self, resolved_theme):
        """Refresh theme-dependent UI details after ThemeManager changes QSS."""
        is_dark = resolved_theme == THEME_DARK
        if hasattr(self, "theme_btn"):
            self.theme_btn.setText("☾ Dark" if is_dark else "☀ Light")
            self.theme_btn.setToolTip("Switch to light mode" if is_dark else "Switch to dark mode")
        if hasattr(self, "theme_status_label"):
            self.theme_status_label.setText("Dark mode" if is_dark else "Light mode")
        if hasattr(self, "component_lists"):
            self._populate_component_lists()

    # ------------------------------------------------------------------
    # Resolution/full screen compatibility
    # ------------------------------------------------------------------
    def _lock_splitter_handles(self):
        """Compatibility no-op retained for older callers."""
        return

    def _release_main_region_widths(self):
        """Compatibility no-op; overlay drawers do not reserve layout width."""
        return

    def _apply_main_region_proportions(self):
        """Compatibility hook that now realigns fixed-width overlay drawers."""
        self._position_overlay_drawers()

    def _apply_vertical_layout_profile(self):
        """Compatibility no-op; drawers naturally use available height."""
        return

    def apply_resolution_preset(self, key):
        """Apply a saved window preset and realign workspace overlays."""
        if self.isFullScreen():
            self.showNormal()
        applied_key = ResolutionManager.apply_to_window(self, key)
        self._windowed_resolution_key = applied_key or key
        self._position_overlay_drawers()
        if hasattr(self, "full_screen_btn"):
            self.full_screen_btn.setText("⛶ Full Screen")
        return applied_key

    def enter_full_screen(self):
        """Enter full-screen mode while preserving overlay alignment."""
        if self.isFullScreen():
            return
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.showFullScreen()
        self.full_screen_btn.setText("⛶ Exit Full Screen")
        QTimer.singleShot(0, self._position_overlay_drawers)

    def exit_full_screen(self):
        """Leave full-screen mode and restore the saved window preset."""
        if not self.isFullScreen():
            return
        self.showNormal()
        self.full_screen_btn.setText("⛶ Full Screen")
        resolution_key = getattr(self, "_windowed_resolution_key", ResolutionManager.load_selected_resolution())
        QTimer.singleShot(0, lambda: self.apply_resolution_preset(resolution_key))

    def toggle_full_screen(self):
        """Switch between full-screen and configured windowed mode."""
        if self.isFullScreen():
            self.exit_full_screen()
        else:
            self.enter_full_screen()

    # ------------------------------------------------------------------
    # Component and value synchronization
    # ------------------------------------------------------------------
    def toggle_value_category(self, comp_type, expanded):
        """Expand or collapse one component type in the value drawer."""
        section = self.value_category_sections.get(comp_type)
        if section is not None:
            section["content"].setVisible(expanded)

    def on_component_selected(self, item):
        """Arm the canvas to place the palette component selected by the user."""
        comp_type = item.data(Qt.UserRole)
        if comp_type is None:
            return
        self.canvas.set_selected_component(comp_type)
        self.status_label.setText(f"Selected: {comp_type.value} — click the canvas to place one.")

    def on_component_added(self, component):
        """Create a value editor box when a new component is placed."""
        comp_type = component.comp_type
        self.status_label.setText(f"Added: {comp_type.value}")
        for component_list in getattr(self, "component_lists", []):
            component_list.clearSelection()
            component_list.setCurrentItem(None)
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

        # New placement and file import share one value-editor construction
        # path so labels, units, and signal wiring cannot drift apart.
        self._create_value_widget_for_component(component)

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

    # ------------------------------------------------------------------
    # Help, settings, and AI request lifecycle
    # ------------------------------------------------------------------
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
        if hasattr(self, "workspace"):
            self.workspace.setEnabled(not busy)
        if hasattr(self, "top_toolbar"):
            self.top_toolbar.setEnabled(not busy)
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

    # ------------------------------------------------------------------
    # Circuit file import and export
    # ------------------------------------------------------------------
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
        """Build a value editor shared by new and imported components."""
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

    # ------------------------------------------------------------------
    # Circuit references and live validation comments
    # ------------------------------------------------------------------
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
        """Refresh live drawer comments for missing values and circuit checks."""
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

    # ------------------------------------------------------------------
    # Window-level keyboard, resize, and shutdown events
    # ------------------------------------------------------------------
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
        """Keep overlay drawers aligned with the canvas workspace."""
        super().resizeEvent(event)
        self._position_overlay_drawers()

    def closeEvent(self, event):
        """Avoid tearing down the window while an AI worker thread is active."""
        if self._ai_request_in_progress:
            event.ignore()
            return
        super().closeEvent(event)
