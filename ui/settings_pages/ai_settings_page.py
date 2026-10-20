"""
AI settings page: provider selection, API key, model discovery, test, and
save/load behavior moved from the old standalone dialog.
"""

from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ai_assistant.providers import AVAILABLE_PROVIDERS, OllamaProvider, create_provider
from ai_assistant.settings_manager import (
    SECRET_PROVIDER_KEYS,
    load_api_key,
    load_settings,
    save_api_key,
    save_settings,
)
from ai_engine.model_discovery import get_available_models


_ALL_PROVIDER_CHOICES = [
    ("ollama", "Ollama Local (default)"),
    ("gemini", "Gemini"),
    ("openai", "OpenAI"),
    ("nvidia", "NVIDIA AI"),
    ("custom", "Custom"),
    ("manual", "Manual (copy prompt only)"),
]

PROVIDER_CHOICES = [
    (key, label) for key, label in _ALL_PROVIDER_CHOICES if AVAILABLE_PROVIDERS.get(key, False)
]

DISCOVERY_CAPABLE_PROVIDERS = {"gemini", "ollama", "nvidia", "openai"}


class AISettingsPage(QWidget):
    """Widget page for configuring and testing the AI provider connection."""

    def __init__(self, parent=None):
        """Build provider controls and load saved per-provider drafts."""
        super().__init__(parent)
        self._cached_models = []
        self.provider_drafts = {}
        self._current_provider = None
        self._loading_provider = False
        self._key_load_failed = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("AI")
        title.setProperty("role", "pageTitle")
        layout.addWidget(title)

        form_card = QWidget()
        form_card.setProperty("role", "settingsCard")
        form_layout_outer = QVBoxLayout(form_card)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.provider_combo = QComboBox()
        self.provider_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for key, label in PROVIDER_CHOICES:
            self.provider_combo.addItem(label, key)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Provider:", self.provider_combo)

        self.api_key_input = QLineEdit()
        self.api_key_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        form.addRow("API Key:", self.api_key_input)

        self.model_combo = QComboBox()
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.model_combo.setEditable(True)
        form.addRow("Model:", self.model_combo)

        self.refresh_models_btn = QPushButton("Refresh Models")
        self.refresh_models_btn.clicked.connect(self.refresh_models)
        form.addRow("", self.refresh_models_btn)

        self.endpoint_input = QLineEdit()
        self.endpoint_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        form.addRow("Server / Endpoint:", self.endpoint_input)

        form_layout_outer.addLayout(form)
        layout.addWidget(form_card)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self.test_connection)
        layout.addWidget(self.test_btn, 0)
        layout.addStretch(1)

        self.load_current_settings()
        self._on_provider_changed()

    def load_current_settings(self):
        """Reload saved provider state and refresh all visible controls."""
        settings = load_settings()
        provider_settings = settings.get("providers") or {}
        for key, _label in PROVIDER_CHOICES:
            state = provider_settings.get(key) or {}
            api_key = ""
            if key in SECRET_PROVIDER_KEYS:
                try:
                    api_key = load_api_key(key)
                except RuntimeError as exc:
                    self._key_load_failed.add(key)
                    self._set_status(str(exc), "error")
            self.provider_drafts[key] = {
                "api_key": api_key,
                "model": state.get("model", ""),
                "endpoint": state.get("endpoint", ""),
                "cached_models": list(state.get("cached_models") or []),
                "last_model_refresh": state.get("last_model_refresh", ""),
            }

        index = self.provider_combo.findData(settings["provider"])
        if index >= 0:
            self.provider_combo.setCurrentIndex(index)
        self._load_provider_into_controls(self.provider_combo.currentData())

    def current_settings(self):
        """Return a settings dictionary reflecting the current form state."""
        provider = self.provider_combo.currentData()
        self._save_current_provider_draft()
        draft = self.provider_drafts.get(provider, {})
        return {
            "provider": provider,
            "api_key": draft.get("api_key", ""),
            "model": draft.get("model", ""),
            "endpoint": draft.get("endpoint", ""),
            "cached_models": list(draft.get("cached_models") or []),
            "last_model_refresh": draft.get("last_model_refresh", ""),
        }

    def _on_provider_changed(self):
        """Save the previous draft and load controls for the new provider."""
        if self._loading_provider:
            return
        if self._current_provider is not None:
            self._save_current_provider_draft()
        provider = self.provider_combo.currentData()
        self._load_provider_into_controls(provider)
        self._update_provider_controls(provider)
        self._current_provider = provider

    def _save_current_provider_draft(self):
        """Copy visible control values into the active provider's draft."""
        provider = self._current_provider or self.provider_combo.currentData()
        if not provider:
            return
        draft = self.provider_drafts.setdefault(provider, {})
        draft["api_key"] = self.api_key_input.text().strip()
        draft["model"] = self.model_combo.currentText().strip()
        draft["endpoint"] = self.endpoint_input.text().strip()
        draft["cached_models"] = list(self._cached_models)

    def _load_provider_into_controls(self, provider):
        """Populate controls from one provider's saved draft.

        Args:
            provider: Provider key present in the page's provider-state map.
        """
        draft = self.provider_drafts.setdefault(
            provider,
            {"api_key": "", "model": "", "endpoint": "", "cached_models": [], "last_model_refresh": ""},
        )
        self._loading_provider = True
        try:
            self.api_key_input.setText(draft.get("api_key", ""))
            self.endpoint_input.setText(draft.get("endpoint", ""))
            self._cached_models = list(draft.get("cached_models") or [])
            self.model_combo.clear()
            if self._cached_models:
                self.model_combo.addItems(self._cached_models)
            self.model_combo.setEditText(draft.get("model", ""))
        finally:
            self._loading_provider = False

        last_refresh = draft.get("last_model_refresh") or ""
        if self._cached_models and last_refresh:
            self._set_status(f"Loaded cached models (last refreshed {last_refresh}).", "info")

    def _update_provider_controls(self, provider):
        """Enable only the fields and actions applicable to provider."""
        is_ollama = provider == "ollama"
        is_manual = provider == "manual"
        supports_discovery = provider in DISCOVERY_CAPABLE_PROVIDERS

        self.refresh_models_btn.setVisible(supports_discovery)
        self.api_key_input.setEnabled(not is_ollama and not is_manual)
        self.model_combo.setEnabled(True)
        self.endpoint_input.setEnabled(True)

        if is_manual:
            self.api_key_input.setPlaceholderText("Enter API key if required")
            self.endpoint_input.setPlaceholderText("https://example.com/v1/chat")
        elif is_ollama:
            self.api_key_input.setPlaceholderText("Not required for Ollama Local")
            self.endpoint_input.setPlaceholderText(OllamaProvider.DEFAULT_SERVER)
        elif provider == "nvidia":
            self.api_key_input.setPlaceholderText("Enter your NVIDIA API Key")
            self.endpoint_input.setPlaceholderText("Leave blank to use the NVIDIA default endpoint")
        elif provider == "openai":
            self.api_key_input.setPlaceholderText("Enter your OpenAI API key")
            self.endpoint_input.setPlaceholderText("Leave blank to use https://api.openai.com/v1/responses")
        else:
            self.api_key_input.setPlaceholderText("")
            self.endpoint_input.setPlaceholderText("Leave blank to use the provider default")

    def refresh_models(self):
        """Discover provider models and repopulate the model selector."""
        self._save_current_provider_draft()
        provider = self.provider_combo.currentData()
        api_key = self.api_key_input.text().strip()
        endpoint = self.endpoint_input.text().strip()
        current_text = self.model_combo.currentText().strip()

        self.refresh_models_btn.setEnabled(False)
        self._set_status("Loading models...", "info")
        QApplication.processEvents()

        try:
            models = get_available_models(provider, api_key=api_key, endpoint=endpoint)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            self._set_status("\u2716 " + self._friendly_refresh_error(str(exc)), "error")
            self.refresh_models_btn.setEnabled(True)
            return

        self.refresh_models_btn.setEnabled(True)

        if not models:
            self._cached_models = []
            self.model_combo.clear()
            if current_text:
                self.model_combo.setEditText(current_text)
            self._save_current_provider_draft()
            self._set_status(
                "No automatically recognized text-generation models were found. "
                "Enter a model name manually.",
                "error",
            )
            return

        self._cached_models = models
        self.model_combo.clear()
        self.model_combo.addItems(models)
        if current_text and current_text in models:
            self.model_combo.setCurrentText(current_text)
        elif current_text:
            self.model_combo.setEditText(current_text)
        else:
            self.model_combo.setCurrentIndex(0)

        self._set_status(f"\u2714 Found {len(models)} models", "success")

        draft = self.provider_drafts.setdefault(provider, {})
        draft["cached_models"] = list(models)
        draft["last_model_refresh"] = datetime.now().isoformat(timespec="seconds")
        self._save_current_provider_draft()

    @staticmethod
    def _friendly_refresh_error(message):
        """Convert low-level discovery failures into concise UI text."""
        lowered = message.lower()
        if "401" in message or "invalid api key" in lowered:
            return "Invalid API key"
        if "403" in message or "permission" in lowered:
            return "API key does not have permission"
        if "429" in message or "rate limit" in lowered:
            return "Rate limit exceeded"
        if "connection failed" in lowered or "not running" in lowered or "cannot reach" in lowered:
            return "Cannot reach AI provider"
        return message

    def test_connection(self):
        """Validate current credentials and endpoint against the provider."""
        data = self.current_settings()
        if data["provider"] == "manual":
            self._set_status(
                "\u2714 Manual mode: no connection needed. Use the Copy Prompt button when solving.",
                "success",
            )
            return
        try:
            provider = create_provider(
                data["provider"], api_key=data["api_key"], model=data["model"], endpoint=data["endpoint"]
            )
            success, message = provider.test_connection()
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            success, message = False, str(exc)

        prefix = "\u2714 " if success else "\u2716 "
        self._set_status(prefix + message, "success" if success else "error")

    def apply_settings(self):
        """Validate, persist, and report the current AI configuration."""
        self._save_current_provider_draft()
        active_provider = self.provider_combo.currentData()
        providers = {}
        for key, draft in self.provider_drafts.items():
            providers[key] = {
                "model": draft.get("model", ""),
                "endpoint": draft.get("endpoint", ""),
                "cached_models": list(draft.get("cached_models") or []),
                "last_model_refresh": draft.get("last_model_refresh", ""),
            }
        save_settings({"active_provider": active_provider, "providers": providers})

        key_errors = []
        for key in SECRET_PROVIDER_KEYS:
            if key in self._key_load_failed and not self.provider_drafts.get(key, {}).get("api_key", ""):
                continue
            try:
                save_api_key(key, self.provider_drafts.get(key, {}).get("api_key", ""))
            except RuntimeError as exc:
                key_errors.append(str(exc))

        if key_errors:
            self._set_status(
                "AI assistant settings saved, but one or more API keys could not be saved securely. "
                + key_errors[0],
                "error",
            )
        else:
            self._set_status("AI assistant settings saved.", "success")

    def save_and_close(self):
        """Backward-compatible alias for applying this page's settings."""
        self.apply_settings()
        QMessageBox.information(self, "Settings Saved", "AI assistant settings have been saved.")

    def _set_status(self, message, state):
        """Update status text and its semantic style property."""
        self.status_label.setText(message)
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
