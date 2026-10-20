"""
Central path helper.

Provides a single, portable way to resolve paths relative to the
application's own location instead of the current working directory or
any hardcoded absolute path. This makes the app work the same way
whether it's run as a Python script or as a frozen PyInstaller .exe.

Usage:
    from app_paths import get_app_path, resource_path

    icon_path = resource_path("assets", "icon.png")
    exports_dir = resource_path("Circuit_exports")
"""

import os
import sys


def get_app_path():
    """Return the directory writable files should live beside.

    - When frozen into a PyInstaller .exe, this is the folder containing
      the executable.
    - When running as a normal Python script, this is the project's
      root folder (the folder containing this file).

    Never falls back to the current working directory, so results stay
    consistent regardless of where the app was launched from.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts):
    """Build an absolute path to a bundled resource.

    PyInstaller one-folder builds place collected data inside ``sys._MEIPASS``
    (the ``_internal`` folder), while the executable itself stays one level up.
    Source runs keep resources beside this file.
    """
    base_path = getattr(sys, "_MEIPASS", None)
    if base_path:
        return os.path.join(base_path, *parts)
    return os.path.join(get_app_path(), *parts)
