"""Persist AI provider preferences while keeping API keys out of QSettings.

Models, endpoints, and cached discovery results use Qt's settings store. Secret
keys use ``keyring`` when available, then Windows Credential Manager as a
fallback; an in-process cache keeps an already loaded key usable for the session.
"""

from PyQt5.QtCore import QSettings
import ctypes
import json
from ctypes import wintypes

ORGANIZATION = "CircuitPrinciplesAssistant"
APPLICATION = "AISettings"
SERVICE_NAME = "CircuitSolver"
SECRET_PROVIDER_KEYS = {"gemini", "nvidia", "openai"}
DEFAULT_PROVIDER_KEYS = ("ollama", "gemini", "openai", "nvidia", "custom", "manual")
_SESSION_API_KEYS = {}

DEFAULT_SETTINGS = {
    "active_provider": "ollama",
    "providers": {
        "ollama": {"model": "", "endpoint": "", "cached_models": [], "last_model_refresh": ""},
        "gemini": {"model": "", "endpoint": "", "cached_models": [], "last_model_refresh": ""},
        "openai": {"model": "", "endpoint": "", "cached_models": [], "last_model_refresh": ""},
        "nvidia": {"model": "", "endpoint": "", "cached_models": [], "last_model_refresh": ""},
        "custom": {"model": "", "endpoint": "", "cached_models": [], "last_model_refresh": ""},
        "manual": {"model": "", "endpoint": "", "cached_models": [], "last_model_refresh": ""},
    },
}


def _settings_store():
    """Return the QSettings store for non-secret AI preferences."""
    return QSettings(QSettings.IniFormat, QSettings.UserScope, ORGANIZATION, APPLICATION)


def _default_provider_state():
    """Return independent mutable copies of every provider's defaults."""
    return {
        key: dict(DEFAULT_SETTINGS["providers"][key])
        for key in DEFAULT_PROVIDER_KEYS
    }


def _load_keyring_module():
    """Import keyring or raise a user-safe secure-storage error."""
    try:
        import keyring  # type: ignore
    except Exception as exc:  # noqa: BLE001 - dependency/backend may be unavailable
        raise RuntimeError("Secure credential storage is unavailable. API key was not saved.") from exc
    return keyring


def _credential_target(provider):
    """Build the stable Windows credential name for a provider key."""
    return f"{SERVICE_NAME}:{provider}"


class _CREDENTIAL(ctypes.Structure):
    """ctypes representation of the Windows CREDENTIALW structure."""
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", wintypes.LPVOID),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_PCREDENTIAL = ctypes.POINTER(_CREDENTIAL)
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


def _advapi32():
    """Load and type the Windows Credential Manager API functions."""
    try:
        library = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    except Exception as exc:  # noqa: BLE001 - non-Windows or restricted runtime
        raise RuntimeError("Windows credential storage is unavailable.") from exc
    library.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
    library.CredWriteW.restype = wintypes.BOOL
    library.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_PCREDENTIAL)]
    library.CredReadW.restype = wintypes.BOOL
    library.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    library.CredDeleteW.restype = wintypes.BOOL
    library.CredFree.argtypes = [wintypes.LPVOID]
    library.CredFree.restype = None
    return library


def _wincred_save(provider, api_key):
    """Store one provider key through Windows Credential Manager."""
    library = _advapi32()
    blob = api_key.encode("utf-16-le")
    blob_buffer = ctypes.create_string_buffer(blob)
    credential = _CREDENTIAL()
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = _credential_target(provider)
    credential.UserName = provider
    credential.Comment = SERVICE_NAME
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(blob_buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    if not library.CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def _wincred_load(provider):
    """Load one provider key from Windows Credential Manager."""
    library = _advapi32()
    credential_pointer = _PCREDENTIAL()
    if not library.CredReadW(
        _credential_target(provider),
        _CRED_TYPE_GENERIC,
        0,
        ctypes.byref(credential_pointer),
    ):
        if ctypes.get_last_error() == _ERROR_NOT_FOUND:
            return ""
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        credential = credential_pointer.contents
        if not credential.CredentialBlob or credential.CredentialBlobSize == 0:
            return ""
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return blob.decode("utf-16-le", errors="ignore")
    finally:
        library.CredFree(credential_pointer)


def _wincred_delete(provider):
    """Delete a provider key from Windows Credential Manager if present."""
    library = _advapi32()
    if not library.CredDeleteW(_credential_target(provider), _CRED_TYPE_GENERIC, 0):
        if ctypes.get_last_error() == _ERROR_NOT_FOUND:
            return
        raise ctypes.WinError(ctypes.get_last_error())


def save_api_key(provider_key: str, api_key: str) -> None:
    """Save/update one provider API key in the OS credential store."""
    provider = (provider_key or "").strip().lower()
    if provider not in SECRET_PROVIDER_KEYS:
        return
    if api_key:
        _SESSION_API_KEYS[provider] = api_key
    else:
        _SESSION_API_KEYS.pop(provider, None)
    try:
        keyring = _load_keyring_module()
        if api_key:
            keyring.set_password(SERVICE_NAME, provider, api_key)
        else:
            delete_api_key(provider)
    except Exception as exc:  # noqa: BLE001 - surface secure-storage failures cleanly
        try:
            if api_key:
                _wincred_save(provider, api_key)
            else:
                _wincred_delete(provider)
        except Exception as fallback_exc:  # noqa: BLE001 - keep message secret-free
            raise RuntimeError("Secure credential storage failed. API key was not saved.") from fallback_exc


def load_api_key(provider_key: str) -> str:
    """Load one provider API key from the OS credential store."""
    provider = (provider_key or "").strip().lower()
    if provider not in SECRET_PROVIDER_KEYS:
        return ""
    try:
        keyring = _load_keyring_module()
        stored_key = keyring.get_password(SERVICE_NAME, provider) or ""
        if stored_key:
            _SESSION_API_KEYS[provider] = stored_key
        return stored_key or _SESSION_API_KEYS.get(provider, "")
    except Exception as exc:  # noqa: BLE001 - do not leak backend details containing secrets
        try:
            stored_key = _wincred_load(provider)
            if stored_key:
                _SESSION_API_KEYS[provider] = stored_key
                return stored_key
        except RuntimeError:
            pass
        if provider in _SESSION_API_KEYS:
            return _SESSION_API_KEYS[provider]
        raise RuntimeError("Secure credential storage failed. API key could not be loaded.") from exc


def delete_api_key(provider_key: str) -> None:
    """Delete one provider API key from the OS credential store."""
    provider = (provider_key or "").strip().lower()
    if provider not in SECRET_PROVIDER_KEYS:
        return
    _SESSION_API_KEYS.pop(provider, None)
    try:
        keyring = _load_keyring_module()
        try:
            keyring.delete_password(SERVICE_NAME, provider)
        except keyring.errors.PasswordDeleteError:
            pass
    except Exception:  # noqa: BLE001 - fallback store may still exist
        pass
    try:
        _wincred_delete(provider)
    except RuntimeError:
        pass


def clear_all_api_keys() -> None:
    """Remove all provider API keys from supported credential stores."""
    for provider in SECRET_PROVIDER_KEYS:
        delete_api_key(provider)


def _provider_state_from_settings(settings, provider):
    """Merge one provider's non-secret settings over clean defaults."""
    providers = settings.get("providers") or {}
    state = dict(DEFAULT_SETTINGS["providers"].get(provider, {}))
    state.update(providers.get(provider) or {})
    state.pop("api_key", None)
    return state


def _flatten_settings(active_provider, providers):
    """Add legacy active-provider keys expected by existing UI callers."""
    active_state = dict(providers.get(active_provider) or {})
    try:
        api_key = load_api_key(active_provider)
    except RuntimeError:
        api_key = ""
    return {
        "active_provider": active_provider,
        "providers": providers,
        "provider": active_provider,
        "api_key": api_key,
        "model": active_state.get("model", ""),
        "endpoint": active_state.get("endpoint", ""),
        "cached_models": list(active_state.get("cached_models") or []),
        "last_model_refresh": active_state.get("last_model_refresh", ""),
    }


def load_settings():
    """Return saved AI settings, with legacy flat keys for current callers."""
    store = _settings_store()
    active_provider = store.value("active_provider", None) or store.value("provider", "ollama")
    active_provider = str(active_provider or "ollama").strip().lower()

    providers_raw = store.value("providers", None)
    providers = _default_provider_state()
    if providers_raw:
        try:
            loaded = json.loads(providers_raw)
            if isinstance(loaded, dict):
                for provider in DEFAULT_PROVIDER_KEYS:
                    providers[provider].update(loaded.get(provider) or {})
                    providers[provider].pop("api_key", None)
        except (TypeError, ValueError):
            pass
    else:
        legacy_provider = active_provider
        providers[legacy_provider].update(
            {
                "model": store.value("model", "") or "",
                "endpoint": store.value("endpoint", "") or "",
                "last_model_refresh": store.value("last_model_refresh", "") or "",
            }
        )
        cached_raw = store.value("cached_models", "[]")
        try:
            providers[legacy_provider]["cached_models"] = json.loads(cached_raw) if cached_raw else []
        except (TypeError, ValueError):
            providers[legacy_provider]["cached_models"] = []

    if active_provider not in providers:
        active_provider = "ollama"
    return _flatten_settings(active_provider, providers)


def save_settings(settings):
    """Persist non-secret provider settings in QSettings."""
    store = _settings_store()
    active_provider = (settings.get("active_provider") or settings.get("provider") or "ollama").strip().lower()
    providers = _default_provider_state()

    if isinstance(settings.get("providers"), dict):
        for provider in DEFAULT_PROVIDER_KEYS:
            providers[provider].update(settings["providers"].get(provider) or {})
            providers[provider].pop("api_key", None)
    else:
        provider = active_provider
        providers[provider].update(
            {
                "model": settings.get("model", ""),
                "endpoint": settings.get("endpoint", ""),
                "cached_models": list(settings.get("cached_models") or []),
                "last_model_refresh": settings.get("last_model_refresh", ""),
            }
        )

    store.setValue("active_provider", active_provider)
    store.setValue("provider", active_provider)
    store.setValue("providers", json.dumps(providers))
    store.remove("api_key")
    store.remove("model")
    store.remove("endpoint")
    store.remove("cached_models")
    store.remove("last_model_refresh")
    store.sync()


def _as_bool(value):
    """Interpret QSettings string booleans consistently with Python values."""
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def is_first_launch():
    """True the very first time the app checks AI settings (never saved before)."""
    store = _settings_store()
    return not _as_bool(store.value("first_launch_seen", False))


def mark_first_launch_seen():
    """Record that the first-launch AI availability check has already run."""
    store = _settings_store()
    store.setValue("first_launch_seen", True)
    store.sync()


def is_configured(settings):
    """Return True if enough information is present to attempt an AI request."""
    provider = settings.get("provider")
    if provider == "manual":
        return False
    if provider == "ollama":
        return True
    if provider == "custom":
        return bool(settings.get("endpoint"))
    return bool(settings.get("api_key"))
