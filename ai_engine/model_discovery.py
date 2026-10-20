"""
Model Discovery: ask a configured AI provider which models it currently
has available, instead of relying on a hardcoded dropdown list.

This module does not implement any HTTP calls itself -- it only delegates
to the `list_models()` method already provided by each provider class in
ui/ai_assistant/providers.py, so the existing provider class structure is
left untouched.

Manual mode is intentionally NOT handled here: it never performs
automatic discovery, the user types the endpoint/model/key by hand.
"""

from ai_assistant.providers import GeminiProvider, NvidiaProvider, OpenAIProvider, OllamaProvider
from ai_engine.model_filters import filter_text_models

# Providers that support automatic model discovery.
DISCOVERY_PROVIDERS = {
    "gemini": GeminiProvider,
    "nvidia": NvidiaProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}


def get_available_models(provider, api_key=None, endpoint=None):
    """
    Return the list of model names currently available for the given
    provider.

    Args:
        provider: provider key ("gemini", "nvidia", "openai", or "ollama", case-insensitive).
        api_key: API key -- required for Gemini, NVIDIA, and OpenAI.
        endpoint: server URL -- used for Ollama (defaults to localhost).

    Returns:
        list[str]: available model names (may be empty).

    Raises:
        RuntimeError: with a readable message if discovery is not
            supported for the provider, or the request fails.
    """
    key = (provider or "").strip().lower()

    provider_cls = DISCOVERY_PROVIDERS.get(key)
    if provider_cls is None:
        raise RuntimeError(f"Model discovery is not supported for provider '{provider}'.")

    instance = provider_cls(api_key=api_key or "", endpoint=endpoint or "")
    models = filter_text_models(key, instance.list_models())
    return sorted(set(models), key=str.lower)
