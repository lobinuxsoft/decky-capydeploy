"""Path sandbox — restricts filesystem access to allowed root directories."""

from __future__ import annotations

import os
from pathlib import Path

# Limits — must match crates/protocol/src/constants.rs
FS_MAX_LIST_ENTRIES = 10_000

# Cached allowed roots.
_ALLOWED_ROOTS: list[Path] | None = None


def get_allowed_roots() -> list[Path]:
    """Build allowed roots lazily (home + /run/media).

    Uses abspath (not resolve) to avoid symlink issues on immutable distros
    where /home -> /var/home.
    """
    global _ALLOWED_ROOTS
    if _ALLOWED_ROOTS is not None:
        return _ALLOWED_ROOTS

    roots: list[Path] = []
    home = Path.home()
    if home.exists():
        roots.append(Path(os.path.abspath(home)))

    media = Path("/run/media")
    if media.exists():
        roots.append(Path(os.path.abspath(media)))

    _ALLOWED_ROOTS = roots
    return roots


def validate_path(raw: str) -> Path:
    """Resolve and validate a path against the sandbox."""
    if raw == "~" or raw.startswith("~/"):
        p = Path.home() / raw[2:] if raw.startswith("~/") else Path.home()
    else:
        p = Path(raw)

    absolute = Path(os.path.abspath(p))
    for root in get_allowed_roots():
        try:
            absolute.relative_to(root)
            return absolute
        except ValueError:
            continue

    raise ValueError(f"access denied: {absolute} is outside allowed roots")


def validate_new_path(raw: str) -> Path:
    """Validate a path whose target may not exist yet (parent must be in sandbox)."""
    if raw == "~" or raw.startswith("~/"):
        p = Path.home() / raw[2:] if raw.startswith("~/") else Path.home()
    else:
        p = Path(raw)

    parent = Path(os.path.abspath(p.parent))
    for root in get_allowed_roots():
        try:
            parent.relative_to(root)
            return parent / p.name
        except ValueError:
            continue

    raise ValueError(f"access denied: {p} is outside allowed roots")
