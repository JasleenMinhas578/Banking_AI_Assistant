"""The MCP server's only way to reach the bank: HTTP calls to the bank API.

Every call carries the caller's session token, so the bank API re-checks the
session, verification, ownership and limits itself. This client holds no
database credentials and makes no decisions.
"""

from typing import Any, Protocol
from uuid import UUID

import httpx

JSON = dict[str, Any]


class BankApiError(Exception):
    """The bank API refused or failed. code is the bank's stable error code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class BankApi(Protocol):
    """What the tools need from the bank. The real client and test fakes both fit."""

    async def get_accounts(self, token: str) -> list[JSON]: ...
    async def get_transactions(self, token: str, account_id: UUID, limit: int) -> JSON: ...
    async def get_cards(self, token: str) -> list[JSON]: ...
    async def freeze_card(self, token: str, card_id: UUID) -> JSON: ...
    async def get_disputes(self, token: str) -> list[JSON]: ...
    async def open_dispute(self, token: str, transaction_id: UUID, reason: str) -> JSON: ...
    async def create_transfer(
        self, token: str, from_id: UUID, to_id: UUID, amount_cents: int, idempotency_key: str
    ) -> JSON: ...


class BankClient:
    """Calls the bank API over HTTP. Retries once, only when the bank didn't answer.

    Retrying is safe for every call here: reads change nothing, freezing and
    disputes are idempotent in the bank, and transfers carry an Idempotency-Key.
    """

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def get_accounts(self, token: str) -> list[JSON]:
        body = await self._call("GET", "/accounts", token)
        return list(body["accounts"])

    async def get_transactions(self, token: str, account_id: UUID, limit: int) -> JSON:
        return await self._call(
            "GET", f"/accounts/{account_id}/transactions", token, params={"limit": limit}
        )

    async def get_cards(self, token: str) -> list[JSON]:
        body = await self._call("GET", "/cards", token)
        return list(body["cards"])

    async def freeze_card(self, token: str, card_id: UUID) -> JSON:
        return await self._call("POST", f"/cards/{card_id}/freeze", token)

    async def get_disputes(self, token: str) -> list[JSON]:
        body = await self._call("GET", "/disputes", token)
        return list(body["disputes"])

    async def open_dispute(self, token: str, transaction_id: UUID, reason: str) -> JSON:
        return await self._call(
            "POST",
            "/disputes",
            token,
            json={"transaction_id": str(transaction_id), "reason": reason},
        )

    async def create_transfer(
        self, token: str, from_id: UUID, to_id: UUID, amount_cents: int, idempotency_key: str
    ) -> JSON:
        return await self._call(
            "POST",
            "/transfers",
            token,
            json={
                "from_account_id": str(from_id),
                "to_account_id": str(to_id),
                "amount_cents": amount_cents,
            },
            headers={"Idempotency-Key": idempotency_key},
        )

    async def _call(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: dict[str, Any] | None = None,
        json: JSON | None = None,
        headers: dict[str, str] | None = None,
    ) -> JSON:
        """Send one request with the session token; turn any refusal into BankApiError."""
        all_headers = {"Authorization": f"Bearer {token}", **(headers or {})}
        for attempt in (1, 2):
            try:
                response = await self.http.request(
                    method, path, params=params, json=json, headers=all_headers
                )
                break
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt == 2:
                    raise BankApiError(
                        503, "bank_unavailable", "The bank isn't answering right now."
                    ) from exc

        if response.is_success:
            body: JSON = response.json()
            return body
        raise _error_from(response)


def _error_from(response: httpx.Response) -> BankApiError:
    """Read the bank's {"error": {"code", "message"}} shape, with a safe fallback."""
    try:
        error = response.json()["error"]
        return BankApiError(response.status_code, str(error["code"]), str(error["message"]))
    except (ValueError, KeyError, TypeError):
        return BankApiError(response.status_code, "bank_error", "The bank couldn't do that.")
