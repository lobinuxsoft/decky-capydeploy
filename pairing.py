"""
Pairing code and token management for Hub authentication.
"""

import secrets
import string
import time
from typing import Optional

import decky  # type: ignore
from settings import SettingsManager  # type: ignore

PAIRING_CODE_LENGTH = 6
PAIRING_CODE_EXPIRY = 60  # seconds
MAX_FAILED_ATTEMPTS = 3
LOCKOUT_DURATION = 300  # 5 minutes (matches Rust agent)


class PairingManager:
    """Manages pairing codes and tokens for Hub authentication."""

    def __init__(self, settings: SettingsManager):
        self.settings = settings
        self.pending_code: Optional[str] = None
        self.pending_hub_id: Optional[str] = None
        self.pending_hub_name: Optional[str] = None
        self.pending_hub_platform: Optional[str] = None
        self.code_expires_at: float = 0
        self.failed_attempts: int = 0
        self.lockout_until: float = 0

    def generate_code(self, hub_id: str, hub_name: str, hub_platform: str = "") -> str:
        """Generate a new pairing code."""
        self.pending_code = "".join(secrets.choice(string.digits) for _ in range(PAIRING_CODE_LENGTH))
        self.pending_hub_id = hub_id
        self.pending_hub_name = hub_name
        self.pending_hub_platform = hub_platform
        self.code_expires_at = time.time() + PAIRING_CODE_EXPIRY
        return self.pending_code

    def validate_code(self, hub_id: str, code: str) -> Optional[str]:
        """Validate a pairing code and return a token if valid."""
        now = time.time()

        # Check lockout
        if now < self.lockout_until:
            return None

        if not self.pending_code or now > self.code_expires_at:
            return None

        if self.pending_hub_id != hub_id or self.pending_code != code:
            self.failed_attempts += 1
            if self.failed_attempts >= MAX_FAILED_ATTEMPTS:
                self.lockout_until = now + LOCKOUT_DURATION
                self.pending_code = None
                self.failed_attempts = 0
                decky.logger.warning(
                    f"Pairing locked out for {LOCKOUT_DURATION}s after "
                    f"{MAX_FAILED_ATTEMPTS} failed attempts"
                )
            return None

        # Success — reset failures and generate token
        self.failed_attempts = 0
        token = secrets.token_urlsafe(32)

        # Save authorized hub
        authorized = self.settings.getSetting("authorized_hubs", {})
        authorized[hub_id] = {
            "name": self.pending_hub_name,
            "platform": self.pending_hub_platform or "",
            "token": token,
            "paired_at": now,
        }
        self.settings.setSetting("authorized_hubs", authorized)

        # Clear pending
        self.pending_code = None
        self.pending_hub_id = None
        self.pending_hub_name = None
        self.pending_hub_platform = None

        return token

    def validate_token(self, hub_id: str, token: str) -> bool:
        """Check if a token is valid for a hub."""
        authorized = self.settings.getSetting("authorized_hubs", {})
        hub = authorized.get(hub_id)
        return hub is not None and hub.get("token") == token
