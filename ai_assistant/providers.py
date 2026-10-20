"""Provide a common completion interface for local and cloud AI backends.

Each provider translates the shared prompt into its HTTP schema, extracts plain
response text, discovers models where supported, and converts common transport
failures into readable UI messages. Network transport uses standard-library
``urllib``; provider availability for settings is controlled near the bottom.
"""

import json
import socket
import urllib.error
import urllib.request


class AIProvider:
    """Common interface every AI backend implements."""

    def __init__(self, api_key="", model="", endpoint=""):
        """Store credentials and optional model/endpoint overrides."""
        self.api_key = api_key or ""
        self.model = model or ""
        self.endpoint = endpoint or ""

    def send_prompt(self, prompt, timeout=30):
        """Send the prompt to the provider and return the raw (parsed JSON) response."""
        raise NotImplementedError

    def receive_response(self, raw_response):
        """Extract the plain-text answer out of a raw provider response."""
        raise NotImplementedError

    def get_completion(self, prompt, timeout=120):
        """Convenience helper: send the prompt and return the extracted text."""
        raw_response = self.send_prompt(prompt, timeout=timeout)
        return self.receive_response(raw_response)

    def test_connection(self):
        """Attempt a minimal round trip. Returns (success: bool, message: str)."""
        try:
            text = self.get_completion("Reply with the single word OK.", timeout=15)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            return False, str(exc)
        if text:
            return True, "Connection successful."
        return False, "Provider returned an empty response."

    @staticmethod
    def _post_json(url, payload, headers=None, timeout=30):
        """POST a JSON payload and return the decoded response.

        Args:
            url: Complete destination URL.
            payload: JSON-serializable request body.
            headers: Optional additional HTTP headers.
            timeout: Network timeout in seconds.
        """
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Connection failed: {exc.reason}") from exc

    @staticmethod
    def _get_json(url, headers=None, timeout=10):
        """GET a URL and return its decoded JSON response."""
        request = urllib.request.Request(url, method="GET")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Connection failed: {exc.reason}") from exc


class GeminiProvider(AIProvider):
    """Google Gemini API provider."""

    DEFAULT_MODEL = "gemini-2.5-flash"
    API_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def _model_name(self):
        """Return the bare model name (no leading 'models/'), falling back to the default."""
        model = (self.model or self.DEFAULT_MODEL).strip()
        if model.startswith("models/"):
            model = model[len("models/"):]
        return model

    def _model_url(self, suffix):
        """Build a v1beta model endpoint, generating the 'models/{name}' path dynamically."""
        model = self._model_name()
        return f"{self.API_BASE}/models/{model}{suffix}?key={self.api_key}"

    def send_prompt(self, prompt, timeout=30):
        """Send prompt through Gemini's generateContent endpoint."""
        if not self.api_key:
            raise RuntimeError("Gemini API key is required.")
        url = self._model_url(":generateContent")
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            return self._post_json(url, payload, timeout=timeout)
        except RuntimeError as exc:
            raise RuntimeError(self._friendly_error(str(exc))) from exc

    def receive_response(self, raw_response):
        """Extract concatenated candidate text from a Gemini response."""
        try:
            parts = raw_response["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts).strip()
        except (KeyError, IndexError, TypeError):
            return ""

    def list_models(self, timeout=10):
        """GET {API_BASE}/models -- return model names that support generateContent."""
        if not self.api_key:
            raise RuntimeError("Gemini API key is required.")
        url = f"{self.API_BASE}/models?key={self.api_key}"
        try:
            data = self._get_json(url, timeout=timeout)
        except RuntimeError as exc:
            raise RuntimeError(self._friendly_error(str(exc))) from exc
        models = data.get("models", []) if isinstance(data, dict) else []
        names = []
        for entry in models:
            methods = entry.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            name = entry.get("name") or ""
            if name.startswith("models/"):
                name = name[len("models/"):]
            if name:
                names.append(name)
        return names

    def test_connection(self):
        """Send a minimal generateContent request using the selected model."""
        try:
            text = self.get_completion("Reply with OK", timeout=15)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            return False, str(exc)
        if text:
            return True, f"Connected. Model '{self._model_name()}' replied: {text[:80]}"
        return False, "Provider returned an empty response."

    @staticmethod
    def _friendly_error(message):
        """Translate raw HTTP error text into a clearer, actionable message."""
        if "HTTP 401" in message:
            return "Invalid API key"
        if "HTTP 403" in message:
            return "API key does not have permission"
        if "HTTP 404" in message:
            return "Model unavailable or incorrect model name"
        if "HTTP 429" in message:
            return "Rate limit exceeded"
        return message


class OpenAIProvider(AIProvider):
    """Official OpenAI Responses API provider."""

    API_BASE = "https://api.openai.com/v1"
    RESPONSES_ENDPOINT = f"{API_BASE}/responses"
    MODELS_ENDPOINT = f"{API_BASE}/models"

    def _model_name(self):
        """Return the selected OpenAI model or raise a configuration error."""
        model = (self.model or "").strip()
        if not model:
            raise RuntimeError("Please enter or select an OpenAI model.")
        return model

    def _headers(self):
        """Return authorization headers for the configured OpenAI key."""
        if not self.api_key:
            raise RuntimeError("OpenAI API key is required.")
        return {"Authorization": f"Bearer {self.api_key}"}

    def send_prompt(self, prompt, timeout=60):
        """Submit prompt input through the OpenAI Responses API."""
        payload = {
            "model": self._model_name(),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                }
            ],
        }
        try:
            return self._post_json(
                self.endpoint.strip() if self.endpoint else self.RESPONSES_ENDPOINT,
                payload,
                headers=self._headers(),
                timeout=timeout,
            )
        except (TimeoutError, socket.timeout) as exc:
            raise RuntimeError("The OpenAI request timed out.") from exc
        except RuntimeError as exc:
            raise RuntimeError(self._friendly_error(str(exc))) from exc

    def receive_response(self, raw_response):
        """Extract text from supported OpenAI Responses API shapes."""
        texts = []

        output_text = raw_response.get("output_text") if isinstance(raw_response, dict) else None
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        outputs = raw_response.get("output") if isinstance(raw_response, dict) else None
        if isinstance(outputs, list):
            for item in outputs:
                content_items = item.get("content") if isinstance(item, dict) else None
                if not isinstance(content_items, list):
                    continue
                for content in content_items:
                    if not isinstance(content, dict):
                        continue
                    if content.get("type") in {"output_text", "text"}:
                        text = content.get("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text.strip())
                        elif isinstance(text, dict):
                            value = text.get("value")
                            if isinstance(value, str) and value.strip():
                                texts.append(value.strip())

        if texts:
            return "\n".join(texts).strip()

        keys = ", ".join(sorted(raw_response.keys())) if isinstance(raw_response, dict) else type(raw_response).__name__
        raise RuntimeError(f"Unexpected OpenAI response structure; no text output found. Top-level keys: {keys}")

    def list_models(self, timeout=15):
        """Return raw model records from OpenAI's models endpoint."""
        try:
            data = self._get_json(self.MODELS_ENDPOINT, headers=self._headers(), timeout=timeout)
        except (TimeoutError, socket.timeout) as exc:
            raise RuntimeError("The OpenAI request timed out.") from exc
        except RuntimeError as exc:
            raise RuntimeError(self._friendly_error(str(exc))) from exc
        return data.get("data", []) if isinstance(data, dict) else []

    def test_connection(self):
        """Run a minimal OpenAI completion and return UI status text."""
        try:
            reply = self.get_completion("Reply only with OK.", timeout=20)
        except Exception as exc:  # noqa: BLE001 - surface readable provider failures
            return False, str(exc)
        return (
            True,
            "Connected successfully.\n"
            "Provider: OpenAI\n"
            f"Model: {self.model}\n"
            f"Reply: {reply[:80]}",
        )

    @staticmethod
    def _friendly_error(message):
        """Translate common OpenAI HTTP failures into actionable text."""
        if "timed out" in message.lower():
            return "The OpenAI request timed out."
        if "HTTP 401" in message:
            return "Invalid OpenAI API key."
        if "HTTP 403" in message:
            return "The OpenAI API key does not have permission for this request."
        if "HTTP 404" in message:
            return "The selected OpenAI model or endpoint was not found."
        if "HTTP 429" in message:
            return "OpenAI rate limit or quota exceeded."
        if any(f"HTTP {code}" in message for code in ("500", "502", "503", "504")):
            return "OpenAI is temporarily unavailable. Try again later."
        return message


class OpenAICompatibleProvider(AIProvider):
    """Any OpenAI Chat Completions-compatible API."""

    DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
    DEFAULT_MODEL = "gpt-4o-mini"

    def send_prompt(self, prompt, timeout=30):
        """Submit a Chat Completions-compatible request to the endpoint."""
        url = self.endpoint or self.DEFAULT_ENDPOINT
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model or self.DEFAULT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
        }
        return self._post_json(url, payload, headers=headers, timeout=timeout)

    def receive_response(self, raw_response):
        """Extract assistant content from a Chat Completions response."""
        try:
            return raw_response["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            return ""


class OllamaProvider(AIProvider):
    """
    Local Ollama server (default backend, zero API keys required).

    The app never loads model files itself -- Ollama owns model storage,
    GPU acceleration, and inference; this class only talks to its HTTP API.
    """

    DEFAULT_SERVER = "http://localhost:11434"
    DEFAULT_MODEL = "qwen3.5:9b"
    DEFAULT_OPTIONS = {"temperature": 0.1, "top_p": 0.8}

    @property
    def server_url(self):
        """Return the configured Ollama base URL without a trailing slash."""
        return (self.endpoint or self.DEFAULT_SERVER).rstrip("/")

    def list_models(self, timeout=10):
        """GET {server}/api/tags -- return the list of installed model names."""
        url = f"{self.server_url}/api/tags"
        try:
            data = self._get_json(url, timeout=timeout)
        except RuntimeError as exc:
            raise RuntimeError(f"Ollama is not running at {self.server_url} ({exc})") from exc
        models = data.get("models", []) if isinstance(data, dict) else []
        names = [entry.get("name") or entry.get("model") for entry in models]
        return [name for name in names if name]

    def test_connection(self):
        """GET /api/tags: verify Ollama is running and list installed models."""
        try:
            models = self.list_models(timeout=10)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            return False, f"Ollama is not running ({exc})"
        if models:
            return True, "Ollama Connected. Installed models: " + ", ".join(models)
        return True, "Ollama Connected. No models are installed yet (try: ollama pull " + self.DEFAULT_MODEL + ")"

    def send_prompt(self, prompt, timeout=120):
        """Run a non-streaming generation request against local Ollama."""
        model = self.model or self.DEFAULT_MODEL
        url = f"{self.server_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": dict(self.DEFAULT_OPTIONS),
        }
        try:
            return self._post_json(url, payload, timeout=timeout)
        except RuntimeError as exc:
            message = str(exc)
            if "HTTP 404" in message or "not found" in message.lower():
                raise RuntimeError(
                    f'Model "{model}" not found. Run: ollama pull {model}'
                ) from exc
            if "Connection failed" in message:
                raise RuntimeError(
                    f"Ollama is not running at {self.server_url}. "
                    "Install/start Ollama or choose another AI provider."
                ) from exc
            raise

    def receive_response(self, raw_response):
        """Extract generated text from an Ollama response object."""
        return (raw_response.get("response") or "").strip()
    

class NvidiaProvider(AIProvider):
    """
    NVIDIA NIM API Provider.

    Supports:
        • NVIDIA-hosted LLMs
        • OpenAI-compatible Chat Completions API
        • Automatic model discovery
    """

    API_BASE = "https://integrate.api.nvidia.com/v1"

    DEFAULT_ENDPOINT = f"{API_BASE}/chat/completions"
    MODELS_ENDPOINT = f"{API_BASE}/models"

    DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"

    def send_prompt(self, prompt, timeout=60):
        """Submit prompt through NVIDIA's Chat Completions endpoint."""
        if not self.api_key:
            raise RuntimeError("NVIDIA API key is required.")

        url = self.endpoint.strip() if self.endpoint else self.DEFAULT_ENDPOINT

        model = (self.model or self.DEFAULT_MODEL).strip()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": 0.2,
            "max_tokens": 4096,
        }

        try:
            return self._post_json(
                url,
                payload,
                headers=headers,
                timeout=timeout,
            )
        except RuntimeError as exc:
            raise RuntimeError(self._friendly_error(str(exc))) from exc

    def receive_response(self, raw_response):
        """Extract assistant content or report an unexpected NVIDIA schema."""
        try:
            return raw_response["choices"][0]["message"]["content"].strip()

        except (KeyError, IndexError, TypeError):
            raise RuntimeError(
                f"Unexpected NVIDIA response:\n{raw_response}"
            )

    def list_models(self, timeout=15):
        """
        Return all models reported by NVIDIA.

        Filtering is intentionally left to the UI or a future release
        because NVIDIA's metadata changes over time.
        """

        if not self.api_key:
            raise RuntimeError("NVIDIA API key is required.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            data = self._get_json(
                self.MODELS_ENDPOINT,
                headers=headers,
                timeout=timeout,
            )
        except RuntimeError as exc:
            raise RuntimeError(self._friendly_error(str(exc))) from exc

        return data.get("data", []) if isinstance(data, dict) else []

    def test_connection(self):
        """
        Verify the API key by sending a small completion request using the
        currently selected model.
        """

        if not self.model:
            return (
                False,
                "Please select a model before testing the connection."
            )

        try:
            reply = self.get_completion(
                "Reply only with OK.",
                timeout=20,
            )
        except Exception as exc:
            return False, str(exc)

        return (
            True,
            f"Connected successfully.\n"
            f"Model: {self.model}\n"
            f"Reply: {reply[:80]}"
        )

    @staticmethod
    def _friendly_error(message):
        """
        Convert HTTP errors into user-friendly messages.
        """

        if "HTTP 401" in message:
            return "Invalid NVIDIA API key."

        if "HTTP 403" in message:
            return "API key does not have permission."

        if "HTTP 404" in message:
            return (
                "The selected model or endpoint could not be found."
            )

        if "HTTP 410" in message:
            return (
                "The selected model has been retired by NVIDIA. "
                "Refresh the model list and choose another."
            )

        if "HTTP 429" in message:
            return "NVIDIA rate limit exceeded."

        if "Connection failed" in message:
            return "Unable to connect to NVIDIA servers."

        return message
    


class CustomProvider(OpenAICompatibleProvider):
    """User-supplied endpoint, assumed OpenAI Chat Completions-compatible."""


PROVIDER_REGISTRY = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
    "nvidia": NvidiaProvider,
    "custom": CustomProvider,
}

# Temporary provider availability switch: providers set to False are kept
# fully implemented (nothing is deleted) but hidden from the settings UI
# until they are finished/re-enabled in a future version.
AVAILABLE_PROVIDERS = {
    "gemini": True,
    "ollama": True,
    "openai": True,
    "nvidia": True,
    "manual": True,
    "custom": False,
}


def create_provider(provider_key, api_key="", model="", endpoint=""):
    """Factory: build the right AIProvider subclass for the given provider key."""
    provider_cls = PROVIDER_REGISTRY.get(provider_key)
    if provider_cls is None:
        raise ValueError(f"Unknown AI provider: {provider_key!r}")
    return provider_cls(api_key=api_key, model=model, endpoint=endpoint)
