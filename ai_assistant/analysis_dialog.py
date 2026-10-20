"""
AI Analysis window: lets the user choose an analysis mode (complete
circuit analysis, solve a missing value, or find a specific component
quantity), pick a component/quantity where relevant, and builds the
resulting AnalysisRequest for the PromptBuilder.
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QPushButton, QLabel, QLineEdit, QMessageBox, QSizePolicy,
)
from PyQt5.QtCore import QTimer

from ai_assistant.analysis_request import (
    AnalysisMode, AnalysisRequest, QUANTITY_OPTIONS_BY_TYPE, SolvingMethod,
)

MODE_ORDER = [
    AnalysisMode.FULL_ANALYSIS,
    AnalysisMode.SOLVE_MISSING_VALUE,
    AnalysisMode.COMPONENT_ANALYSIS,
]

MODE_LABELS = {
    AnalysisMode.FULL_ANALYSIS: "1. Complete Circuit Analysis",
    AnalysisMode.SOLVE_MISSING_VALUE: "2. Solve Missing Component Value",
    AnalysisMode.COMPONENT_ANALYSIS: "3. Find Component Quantity",
}

METHOD_ORDER = [
    SolvingMethod.AUTO,
    SolvingMethod.NODAL,
    SolvingMethod.MESH,
    SolvingMethod.SUPERPOSITION,
    SolvingMethod.USER_DEFINED,
]


class AnalysisDialog(QDialog):
    """Collects an AnalysisRequest describing what the AI should determine."""

    def __init__(self, value_components, reference_name_getter, parent=None):
        """Initialize controls for the available value-bearing components.

        Args:
            value_components: Components that can participate in an analysis.
            reference_name_getter: Callable returning a component's UI label.
            parent: Optional owning Qt widget.
        """
        super().__init__(parent)
        self.setWindowTitle("AI Circuit Analysis")
        self.resize(620, 320)
        self.setMinimumSize(560, 280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.value_components = value_components
        self.reference_name_getter = reference_name_getter
        self.result_request = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self.mode_combo = QComboBox()
        self.mode_combo.setEditable(False)
        self.mode_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for mode in MODE_ORDER:
            self.mode_combo.addItem(MODE_LABELS[mode], mode)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        form.addRow("Analysis Mode:", self.mode_combo)

        self.method_label = QLabel("Preferred Method:")
        self.method_combo = QComboBox()
        self.method_combo.setEditable(False)
        self.method_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for method in METHOD_ORDER:
            self.method_combo.addItem(method.value, method)
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        form.addRow(self.method_label, self.method_combo)

        self.custom_method_label = QLabel("Custom Method:")
        self.custom_method_input = QLineEdit()
        self.custom_method_input.setPlaceholderText("Describe the solving method to use")
        self.custom_method_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.custom_method_input.setMinimumHeight(34)
        form.addRow(self.custom_method_label, self.custom_method_input)

        self.component_combo = QComboBox()
        self.component_combo.setEditable(False)
        self.component_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.component_combo.currentIndexChanged.connect(self._on_component_changed)
        form.addRow("Component:", self.component_combo)

        self.quantity_combo = QComboBox()
        self.quantity_combo.setEditable(False)
        self.quantity_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        form.addRow("Quantity:", self.quantity_combo)

        layout.addLayout(form)

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setProperty("role", "mutedText")
        layout.addWidget(self.hint_label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        continue_btn = QPushButton("Continue")
        continue_btn.clicked.connect(self._on_continue)
        button_row.addWidget(continue_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

        self._on_mode_changed()

    def _current_mode(self):
        """Return the AnalysisMode stored by the selected combo-box row."""
        return self.mode_combo.currentData()

    def _missing_value_components(self):
        """Return components whose editable assigned value is blank."""
        return [
            component for component in self.value_components
            if not (getattr(component, "assigned_value", "") or "").strip()
        ]

    def _on_mode_changed(self):
        """Repopulate and show controls that apply to the selected mode."""
        mode = self._current_mode()
        self.component_combo.blockSignals(True)
        self.component_combo.clear()

        if mode == AnalysisMode.FULL_ANALYSIS:
            self._set_method_visible(False)
            self.component_combo.setEnabled(False)
            self.quantity_combo.clear()
            self.quantity_combo.setEnabled(False)
            self.hint_label.setText(
                "Requests all node voltages, branch currents, and power. Only results are displayed."
            )

        elif mode == AnalysisMode.SOLVE_MISSING_VALUE:
            self._set_method_visible(True)
            self.component_combo.setEnabled(True)
            self.quantity_combo.clear()
            self.quantity_combo.setEnabled(False)
            missing = self._missing_value_components()
            for component in missing:
                self.component_combo.addItem(self.reference_name_getter(component), component)
            if not missing:
                self.hint_label.setText("No components have a missing value. Enter all values, or choose a different mode.")
            else:
                self.hint_label.setText("Select the component whose value should be solved for.")

        elif mode == AnalysisMode.COMPONENT_ANALYSIS:
            self._set_method_visible(True)
            self.component_combo.setEnabled(True)
            self.quantity_combo.setEnabled(True)
            for component in self.value_components:
                self.component_combo.addItem(self.reference_name_getter(component), component)
            self.hint_label.setText("Select a component and the quantity to find.")

        self.component_combo.blockSignals(False)
        self._on_component_changed()

    def _set_method_visible(self, visible):
        """Show or hide method controls for targeted analysis modes.

        Args:
            visible: True when the preferred-method selector is applicable.
        """
        self._method_controls_visible = visible
        self.method_label.setVisible(visible)
        self.method_combo.setVisible(visible)
        self._on_method_changed()

    def _on_method_changed(self):
        """Show the custom-method input only for User-defined selection."""
        show_custom = (
            getattr(self, "_method_controls_visible", False)
            and self.method_combo.currentData() == SolvingMethod.USER_DEFINED
        )
        self.custom_method_label.setVisible(show_custom)
        self.custom_method_input.setVisible(show_custom)
        if show_custom:
            # The row starts hidden. Grow the dialog after Qt has recalculated
            # the form so the newly visible editor cannot be compressed into
            # or painted underneath the next row on high-DPI displays.
            QTimer.singleShot(0, self._ensure_form_fits)

    def _ensure_form_fits(self):
        """Grow, but never unexpectedly shrink, the dialog to its layout hint."""
        if not self.isVisible():
            return
        self.layout().activate()
        size_hint = self.sizeHint()
        self.resize(
            max(self.width(), size_hint.width()),
            max(self.height(), size_hint.height()),
        )

    def _selected_method_values(self):
        """Validate and return the selected method and optional custom text."""
        method = self.method_combo.currentData()
        custom_method = self.custom_method_input.text().strip()
        if method == SolvingMethod.USER_DEFINED and not custom_method:
            QMessageBox.warning(
                self,
                "Custom Method Required",
                "Enter the solving method you want the AI to use.",
            )
            return None, None
        return method, custom_method or None

    def _on_component_changed(self):
        """Load quantity choices supported by the selected component type."""
        self.quantity_combo.clear()
        if self._current_mode() != AnalysisMode.COMPONENT_ANALYSIS:
            return
        component = self.component_combo.currentData()
        if component is None:
            return
        options = QUANTITY_OPTIONS_BY_TYPE.get(component.comp_type, [])
        self.quantity_combo.addItems(options)

    def _on_continue(self):
        """Validate the form, create result_request, and accept the dialog."""
        mode = self._current_mode()

        if mode == AnalysisMode.FULL_ANALYSIS:
            self.result_request = AnalysisRequest(mode=mode)
            self.accept()
            return

        if mode == AnalysisMode.SOLVE_MISSING_VALUE:
            component = self.component_combo.currentData()
            if component is None:
                QMessageBox.warning(self, "No Component", "No component with a missing value is available to select.")
                return
            method, custom_method = self._selected_method_values()
            if method is None:
                return
            self.result_request = AnalysisRequest(
                mode=mode,
                target_component=self.reference_name_getter(component),
                target_component_type=component.comp_type,
                preferred_method=method,
                custom_method=custom_method,
            )
            self.accept()
            return

        if mode == AnalysisMode.COMPONENT_ANALYSIS:
            component = self.component_combo.currentData()
            quantity = self.quantity_combo.currentText().strip()
            if component is None or not quantity:
                QMessageBox.warning(self, "Incomplete Selection", "Please select both a component and a quantity.")
                return
            method, custom_method = self._selected_method_values()
            if method is None:
                return
            self.result_request = AnalysisRequest(
                mode=mode,
                target_component=self.reference_name_getter(component),
                target_component_type=component.comp_type,
                requested_quantity=quantity,
                preferred_method=method,
                custom_method=custom_method,
            )
            self.accept()
            return
