"""PIN checking and session tokens."""

import secrets

import bcrypt

# A hash of a PIN nobody has. When a customer code doesn't exist we still run
# one bcrypt check against this, so a wrong code takes as long as a wrong PIN.
# Otherwise an attacker could time responses to learn which codes are real.
_DUMMY_PIN_HASH = bcrypt.hashpw(b"not-a-real-pin", bcrypt.gensalt()).decode()


class PinVerifier:
    """Checks a PIN against its bcrypt hash."""

    def check(self, pin: str, pin_hash: str | None) -> bool:
        """Return True if the PIN matches. A missing hash always returns False."""
        if pin_hash is None:
            bcrypt.checkpw(pin.encode(), _DUMMY_PIN_HASH.encode())
            return False
        return bcrypt.checkpw(pin.encode(), pin_hash.encode())


def new_session_token() -> str:
    """A long random token that's safe to put in a URL or header."""
    return secrets.token_urlsafe(32)
