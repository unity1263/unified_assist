"""Compatibility package that points repo-root imports at ``src/unified_assist``.

This keeps ``python -m unified_assist.app.minimax_runner`` working from the
repository root without requiring an editable install.
"""

from __future__ import annotations

from pathlib import Path


_PACKAGE_DIR = Path(__file__).resolve().parent
_SOURCE_PACKAGE_DIR = _PACKAGE_DIR.parent / "src" / "unified_assist"

if _SOURCE_PACKAGE_DIR.is_dir():
    __path__ = [str(_SOURCE_PACKAGE_DIR)]
else:
    __path__ = [str(_PACKAGE_DIR)]

__all__ = ["__version__"]
__version__ = "0.1.0"
