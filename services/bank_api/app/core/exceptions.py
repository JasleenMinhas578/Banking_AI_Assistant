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


class SessionAlreadyVerified(BankRefusal):
    """The PIN was already checked for this session. A second check is refused,
    so a wrong PIN can never come back with a success."""

    status_code = 409
    code = "already_verified"
    message = "This session is already verified."


class AccountNotFound(BankRefusal):
    """No such account for this customer.

    We answer 404 whether the account doesn't exist or belongs to someone
    else, so a caller can't discover which account IDs are real.
    """

    status_code = 404
    code = "account_not_found"
    message = "No account with that ID was found for you."


class CardNotFound(BankRefusal):
    """No such card for this customer. 404 for the same reason as AccountNotFound."""

    status_code = 404
    code = "card_not_found"
    message = "No card with that ID was found for you."


class TransactionNotFound(BankRefusal):
    """No such transaction on any of this customer's accounts."""

    status_code = 404
    code = "transaction_not_found"
    message = "No transaction with that ID was found for you."


class DisputeNotAllowed(BankRefusal):
    """The transaction exists and is yours, but POL-003 says it can't be disputed."""

    status_code = 422
    code = "dispute_not_allowed"
    message = "This transaction can't be disputed."


class DisputeWindowClosed(DisputeNotAllowed):
    code = "dispute_window_closed"
    message = "This purchase is past the dispute window."


class TransactionPending(DisputeNotAllowed):
    code = "transaction_pending"
    message = "Pending purchases can't be disputed until they post."


class NotAPurchase(DisputeNotAllowed):
    code = "not_a_purchase"
    message = "Only purchases (money going out) can be disputed."


class StepUpRequired(BankRefusal):
    """Transfers over $1,000 need a one-time code on top of the PIN (POL-004)."""

    status_code = 403
    code = "step_up_required"
    message = "This transfer needs a one-time code. Request one, then try again."


class InvalidOtp(BankRefusal):
    """The one-time code was wrong."""

    status_code = 401
    code = "invalid_otp"
    message = "That code is incorrect."


class OtpExpired(BankRefusal):
    """No live code: it expired, was never requested, or was used up."""

    status_code = 401
    code = "otp_expired"
    message = "That code has expired. Please request a new one."


class OtpAttemptsExhausted(BankRefusal):
    """Too many wrong codes. The code is cancelled."""

    status_code = 401
    code = "otp_attempts_exhausted"
    message = "Too many wrong codes. Please request a new one."


class IdempotencyKeyReused(BankRefusal):
    """The same Idempotency-Key was sent with a different transfer."""

    status_code = 409
    code = "idempotency_key_reused"
    message = "This Idempotency-Key was already used for a different transfer."


class TransferRefused(BankRefusal):
    """The transfer breaks a POL-004 rule. Nothing was moved."""

    status_code = 422
    code = "transfer_refused"
    message = "This transfer isn't allowed."


class SameAccount(TransferRefused):
    code = "same_account"
    message = "The two accounts must be different."


class PerTransferLimitExceeded(TransferRefused):
    code = "per_transfer_limit"
    message = "This transfer is over the per-transfer limit."


class DailyLimitExceeded(TransferRefused):
    code = "daily_limit"
    message = "This transfer would go over today's limit."


class InsufficientFunds(TransferRefused):
    code = "insufficient_funds"
    message = "There isn't enough money in the account for this transfer."


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
