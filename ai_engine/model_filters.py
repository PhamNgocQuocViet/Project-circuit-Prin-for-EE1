"""Provider-neutral filtering for text-generation model dropdowns."""

DENY_KEYWORDS = (
    "embedding",
    "embed",
    "rerank",
    "diffusion",
    "image",
    "vision-only",
    "video",
    "sora",
    "tts",
    "speech",
    "audio",
    "whisper",
    "transcribe",
    "moderation",
    "guard",
    "safety",
    "classifier",
    "detector",
    "segmentation",
)

ALLOW_HINTS = (
    "chat",
    "instruct",
    "reasoning",
    "text",
    "language",
    "llm",
    "gpt",
    "o1",
    "o3",
    "o4",
    "llama",
    "mistral",
    "mixtral",
    "qwen",
    "deepseek",
    "gemini",
    "claude",
    "nemotron",
)


def _model_id(model):
    """Extract a stable model identifier from a string or provider record."""
    if isinstance(model, dict):
        return str(model.get("id") or model.get("name") or model.get("model") or "").strip()
    return str(model or "").strip()


def _metadata_text(metadata):
    """Flatten selected metadata fields into lowercase searchable text."""
    if not isinstance(metadata, dict):
        return ""
    parts = []
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}:{value}")
        elif isinstance(value, list):
            parts.append(f"{key}:{' '.join(str(item) for item in value)}")
        elif isinstance(value, dict):
            parts.append(f"{key}:{_metadata_text(value)}")
    return " ".join(parts).lower()


def _supports_text(metadata):
    """Return whether provider metadata explicitly supports text generation."""
    text = _metadata_text(metadata)
    if not text:
        return None
    positive_pairs = (
        "generatecontent",
        "text generation",
        "text_generation",
        "text-generation",
        "chat",
        "completion",
        "responses",
        "input_text",
        "output_text",
    )
    if any(hint in text for hint in positive_pairs):
        return True
    if "text" in text and "output" in text:
        return True
    return None


def is_text_generation_model(provider_key: str, model_id: str, metadata: dict | None = None) -> bool:
    """Return True when a model is suitable for text/instruction responses."""
    model = (model_id or "").strip()
    if not model:
        return False

    provider = (provider_key or "").strip().lower()
    lowered = model.lower()
    meta_text = _metadata_text(metadata)
    searchable = f"{lowered} {meta_text}"

    if any(keyword in searchable for keyword in DENY_KEYWORDS):
        if "vision" in searchable and any(hint in searchable for hint in ALLOW_HINTS):
            return True
        return False

    metadata_support = _supports_text(metadata)
    if metadata_support is not None:
        return metadata_support

    if provider == "gemini":
        return "embed" not in lowered and "imagen" not in lowered
    if provider == "ollama":
        return "embed" not in lowered
    if provider in {"nvidia", "openai"}:
        return True
    return any(hint in lowered for hint in ALLOW_HINTS) or "/" in model or ":" in model


def filter_text_models(provider_key: str, models: list) -> list[str]:
    """Filter discovered provider models and return unique model IDs."""
    filtered = []
    seen = set()
    for model in models or []:
        model_id = _model_id(model)
        if not model_id:
            continue
        metadata = model if isinstance(model, dict) else None
        if not is_text_generation_model(provider_key, model_id, metadata):
            continue
        if model_id in seen:
            continue
        seen.add(model_id)
        filtered.append(model_id)
    return filtered
