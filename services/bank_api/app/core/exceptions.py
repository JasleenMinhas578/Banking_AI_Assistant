"""Custom exceptions. Each one knows its HTTP status and a stable error code.

There are two families:
- BankRefusal: the bank deliberately said no (wrong PIN, expired session...).
  The request's database work is still committed, so the refusal itself is
  recorded in the audit log and counters.
- Everything else (like DatabaseUnavailable): something broke. All database
  work for the request is rolled back.
"""


class AppError(Exception):
    """Base class for every error the API returns on purpose."""

    status_code = 500
    code = "internal_error"
    message = "Something went wrong."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.message
        super().__init__(self.message)


class DatabaseUnavailable(AppError):
    """The database can't be reached. 503 means 'up, but not ready'."""

    status_code = 503
    code = "database_unavailable"
    message = "The database is not reachable right now."


class BankRefusal(AppError):
    """The bank deliberately refused the request."""

    status_code = 400
    code = "refused"
    message = "The request was refused."


class InvalidCredentials(BankRefusal):
    """Wrong customer code or PIN. Deliberately vague: never says which."""

    status_code = 401
    code = "invalid_credentials"
    message = "The customer code or PIN is incorrect."


class AccountLocked(BankRefusal):
    """Too many wrong PINs. Only a human agent can unlock."""

    status_code = 423
    code = "account_locked"
    message = "This account is locked after too many wrong PINs. A human agent will help."


class VerificationRequired(BankRefusal):
    """The session is live but the caller hasn't passed the PIN check yet.

    401 means "I don't know who you are". 403 means "I know, but you may not
    do this yet".
    """

    status_code = 403
    code = "verification_required"
    message = "Please verify your identity with your PIN first."


class SessionInvalid(BankRefusal):
    """Missing or unknown session token."""

    status_code = 401
    code = "session_invalid"
    message = "No valid session. Start a new session first."


class SessionExpired(BankRefusal):
    """The session sat idle for longer than the timeout."""

    status_code = 401
    code = "session_expired"
    message = "The session timed out. Please start again."
