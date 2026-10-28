"""PINs, one-time codes and session tokens."""

import secrets

import bcrypt

# A hash of a secret nobody has. When a customer code doesn't exist we still run
# one bcrypt check against this, so a wrong code takes as long as a wrong PIN.
# Otherwise an attacker could time responses to learn which codes are real.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-secret", bcrypt.gensalt()).decode()


class PinVerifier:
    """Hashes and checks short secrets (PINs and one-time codes) with bcrypt."""

    def check(self, secret: str, secret_hash: str | None) -> bool:
        """Return True if the secret matches. A missing hash always returns False."""
        if secret_hash is None:
            bcrypt.checkpw(secret.encode(), _DUMMY_HASH.encode())
            return False
        return bcrypt.checkpw(secret.encode(), secret_hash.encode())

    def hash(self, secret: str) -> str:
        """A bcrypt hash, safe to store. The secret itself never is."""
        return bcrypt.hashpw(secret.encode(), bcrypt.gensalt()).decode()


def new_session_token() -> str:
    """A long random token that's safe to put in a URL or header."""
    return secrets.token_urlsafe(32)


def new_one_time_code() -> str:
    """A random 6-digit code, like '048213'."""
    return f"{secrets.randbelow(1_000_000):06d}"
