"""
Shared Steam/system utility functions for CapyDeploy Decky Plugin.
All functions are module-level (no class required).
"""

import os
from pathlib import Path
from typing import Optional

import decky  # type: ignore


def _is_usable_ipv4(ip: str) -> bool:
    """True if the IP is a non-loopback, non-link-local IPv4 address."""
    if not ip or "." not in ip:
        return False
    if ip.startswith("127.") or ip.startswith("169.254."):
        return False
    return True


def get_local_ip() -> Optional[str]:
    """Get the local non-loopback IPv4 address.

    Returns None when the network is not ready (no usable address yet),
    so callers can decide whether to retry or fall back. Note: callers
    that historically expected a string fallback (e.g. "127.0.0.1")
    must be updated.
    """
    import socket

    # Primary: UDP-connect trick reveals the interface that would route
    # outbound traffic. Fast and accurate when the network is up.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if _is_usable_ipv4(ip):
            return ip
    except Exception:
        pass

    # Fallback: enumerate addresses bound to the hostname.
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if _is_usable_ipv4(ip):
                return ip
    except Exception:
        pass

    return None


def detect_platform() -> str:
    """Detect the handheld platform."""
    # Check OS release first (most reliable method)
    try:
        with open("/etc/os-release", "r") as f:
            content = f.read().lower()
            # SteamOS is the real Steam Deck
            if "steamos" in content:
                return "steamdeck"
            if "chimeraos" in content:
                return "chimeraos"
            # Bazzite is NOT a Steam Deck, return linux
            if "bazzite" in content:
                return "linux"
    except Exception:
        pass

    # Check for handheld-specific files (fallback)
    if os.path.exists("/usr/share/plymouth/themes/legion-go"):
        return "legiongologo"
    if os.path.exists("/usr/share/plymouth/themes/rogally"):
        return "rogally"

    # Only check /home/deck if it's a real directory (not a symlink)
    # This avoids false positives on Bazzite which symlinks /home/deck
    try:
        info = os.lstat("/home/deck")
        import stat
        if not stat.S_ISLNK(info.st_mode) and stat.S_ISDIR(info.st_mode):
            return "steamdeck"
    except Exception:
        pass

    return "linux"


def get_user_home() -> str:
    """Get the real user home directory (not /root when running as service)."""
    # Check the standard Steam Deck user first
    if os.path.exists("/home/deck"):
        return "/home/deck"

    try:
        for entry in os.listdir("/home"):
            home_path = f"/home/{entry}"
            if os.path.isdir(home_path) and os.path.exists(f"{home_path}/.steam"):
                return home_path
    except Exception:
        pass

    return str(Path.home())


def expand_path(path: str) -> str:
    """Expand ~ to actual home directory."""
    if path.startswith("~/"):
        return os.path.join(get_user_home(), path[2:])
    return path


def get_steam_dir() -> Optional[str]:
    """Find Steam installation directory."""
    home = get_user_home()
    candidates = [
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".local", "share", "Steam"),
        os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".steam", "steam"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return None


def get_steam_users() -> list:
    """Get Steam users from userdata directory."""
    steam_dir = get_steam_dir()
    if not steam_dir:
        return []
    userdata_dir = os.path.join(steam_dir, "userdata")
    if not os.path.isdir(userdata_dir):
        return []
    users = []
    for entry in os.listdir(userdata_dir):
        entry_path = os.path.join(userdata_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        if not entry.isdigit() or entry == "0":
            continue
        has_shortcuts = os.path.exists(
            os.path.join(entry_path, "config", "shortcuts.vdf")
        )
        users.append({"id": entry, "hasShortcuts": has_shortcuts})
    return users


