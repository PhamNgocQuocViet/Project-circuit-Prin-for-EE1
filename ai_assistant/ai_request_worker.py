"""Qt worker for running provider completion requests off the UI thread."""

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot


class AIRequestWorker(QObject):
    """Run one AI completion request and report the result via signals."""

    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, provider, prompt, timeout=300, parent=None):
        """Store one provider request for execution in a QThread.

        Args:
            provider: AIProvider-compatible completion client.
            prompt: Complete circuit-analysis prompt text.
            timeout: Provider request timeout in seconds.
            parent: Optional owning QObject.
        """
        super().__init__(parent)
        self.provider = provider
        self.prompt = prompt
        self.timeout = timeout

    @pyqtSlot()
    def run(self):
        """Execute the request and emit either finished text or a failure."""
        try:
            response_text = self.provider.get_completion(
                self.prompt,
                timeout=self.timeout,
            )

            if not response_text:
                raise RuntimeError("The AI provider returned an empty response.")

            self.finished.emit(response_text)
        except Exception as exc:  # noqa: BLE001 - route readable provider failures to the UI
            self.failed.emit(str(exc))
