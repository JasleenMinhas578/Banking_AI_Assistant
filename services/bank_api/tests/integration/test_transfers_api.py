"""Transfers and one-time codes end to end, with the seeded demo customers.

Priya: chequing 4821 ($3,240.50), savings 7710 ($12,500.00)
Sam:   chequing 1148 ($42.10),    savings 2209 ($3,100.00)
"""

import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import settings
from app.core.exceptions import BankRefusal
from app.main import app
from app.models.session import Session
from app.repositories.account_repository import AccountRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.transfer_repository import TransferRepository
from app.services.transfer_service import TransferLimits, TransferService
from tests.integration.helpers import account_ids, auth, start_session, step_up, verified_session

PRIYA, SAM, MARCUS = ("C-1001", "2468"), ("C-1004", "9753"), ("C-1002", "1357")


def send(
    client: TestClient, token: str, source: str, target: str, cents: int, key: str | None = None
) -> Response:
    """POST /transfers with a fresh Idempotency-Key unless one is given."""
    return client.post(
        "/transfers",
        headers={**auth(token), "Idempotency-Key": key or str(uuid4())},
        json={"from_account_id": source, "to_account_id": target, "amount_cents": cents},
    )


def balances(db: psycopg.Connection) -> dict[str, int]:
    return dict(db.execute("select last4, balance_cents from accounts").fetchall())


def test_priya_moves_200_to_savings(client: TestClient, db: psycopg.Connection) -> None:
    token = verified_session(client, *PRIYA)
    ids = account_ids(client, token)

    response = send(client, token, ids["4821"], ids["7710"], 20_000)

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["message"].startswith("Moved $200.00 from chequing ••••4821 to savings ••••7710.")
    assert body["from_account"]["balance"] == "$3,040.50"
    assert body["to_account"]["balance"] == "$12,700.00"
    assert balances(db)["4821"] == 304_050
    assert balances(db)["7710"] == 1_270_000


def test_transfer_shows_up_in_both_histories(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)
    ids = account_ids(client, token)
    send(client, token, ids["4821"], ids["7710"], 20_000)

    url = f"/accounts/{ids['7710']}/transactions"
    newest = client.get(url, headers=auth(token)).json()["transactions"][0]

    assert (newest["merchant"], newest["amount"]) == ("Transfer from chequing ••••4821", "$200.00")


def test_repeated_request_moves_money_once(client: TestClient, db: psycopg.Connection) -> None:
    token = verified_session(client, *PRIYA)
    ids = account_ids(client, token)
    first = send(client, token, ids["4821"], ids["7710"], 20_000, key="retry-key-1")

    second = send(client, token, ids["4821"], ids["7710"], 20_000, key="retry-key-1")

    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["transfer"]["reference"] == first.json()["transfer"]["reference"]
    assert balances(db)["4821"] == 304_050
    assert db.execute("select count(*) from transfers").fetchone() == (1,)


def test_same_key_with_a_different_amount_is_refused(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)
    ids = account_ids(client, token)
    send(client, token, ids["4821"], ids["7710"], 20_000, key="retry-key-1")

    response = send(client, token, ids["4821"], ids["7710"], 30_000, key="retry-key-1")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_reused"


def test_sam_cannot_overdraw_his_chequing(client: TestClient, db: psycopg.Connection) -> None:
    token = verified_session(client, *SAM)
    ids = account_ids(client, token)

    response = send(client, token, ids["1148"], ids["2209"], 10_000)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "insufficient_funds"
    assert balances(db)["1148"] == 4_210


def test_over_the_per_transfer_limit_is_refused(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)
    step_up(client, token)
    ids = account_ids(client, token)

    response = send(client, token, ids["7710"], ids["4821"], 250_001)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "per_transfer_limit"


def test_over_1000_needs_a_code_then_works(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)
    ids = account_ids(client, token)

    refused = send(client, token, ids["7710"], ids["4821"], 150_000)
    step_up(client, token)
    allowed = send(client, token, ids["7710"], ids["4821"], 150_000)

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "step_up_required"
    assert allowed.status_code == 200


def test_exactly_1000_needs_no_code(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)
    ids = account_ids(client, token)

    response = send(client, token, ids["7710"], ids["4821"], 100_000)

    assert response.status_code == 200


def test_daily_limit_is_5000_in_total(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)
    step_up(client, token)
    ids = account_ids(client, token)

    first = send(client, token, ids["7710"], ids["4821"], 250_000)
    second = send(client, token, ids["7710"], ids["4821"], 250_000)
    third = send(client, token, ids["7710"], ids["4821"], 1)

    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 422
    assert third.json()["error"]["code"] == "daily_limit"


def test_cannot_send_to_someone_elses_account(client: TestClient, db: psycopg.Connection) -> None:
    marcus = verified_session(client, *MARCUS)
    marcus_chequing = account_ids(client, marcus)["3365"]
    priya = verified_session(client, *PRIYA)

    response = send(client, priya, account_ids(client, priya)["4821"], marcus_chequing, 1_000)

    assert response.status_code == 404
    assert balances(db)["3365"] == 87_520


def test_same_account_is_refused(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)
    chequing = account_ids(client, token)["4821"]

    response = send(client, token, chequing, chequing, 1_000)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "same_account"


def test_missing_idempotency_key_is_rejected(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)
    ids = account_ids(client, token)

    response = client.post(
        "/transfers",
        headers=auth(token),
        json={"from_account_id": ids["4821"], "to_account_id": ids["7710"], "amount_cents": 1_000},
    )

    assert response.status_code == 422


def test_zero_or_negative_amount_is_rejected(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)
    ids = account_ids(client, token)

    assert send(client, token, ids["4821"], ids["7710"], 0).status_code == 422
    assert send(client, token, ids["4821"], ids["7710"], -500).status_code == 422


def test_unverified_session_gets_403(client: TestClient) -> None:
    token = start_session(client)

    response = send(client, token, str(uuid4()), str(uuid4()), 1_000)

    assert response.status_code == 403


def test_there_is_no_way_to_reverse_a_transfer() -> None:
    paths = [getattr(route, "path", "") for route in app.routes]
    assert not any("revers" in path or "refund" in path for path in paths)


def test_wrong_code_then_too_many(client: TestClient) -> None:
    token = verified_session(client, *PRIYA)
    client.post("/sessions/step-up", headers=auth(token))

    def enter(code: str) -> Response:
        return client.post("/sessions/step-up/verify", headers=auth(token), json={"code": code})

    codes = [enter("000000").json()["error"]["code"] for _ in range(3)]

    assert codes == ["invalid_otp", "invalid_otp", "otp_attempts_exhausted"]


def test_expired_code_is_refused(client: TestClient, db: psycopg.Connection) -> None:
    token = verified_session(client, *PRIYA)
    code = client.post("/sessions/step-up", headers=auth(token)).json()["demo_code"]
    db.execute(
        "update sessions set otp_expires_at = now() - interval '1 second' where token = %s",
        (token,),
    )

    response = client.post("/sessions/step-up/verify", headers=auth(token), json={"code": code})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "otp_expired"


def test_code_is_stored_only_as_a_hash(client: TestClient, db: psycopg.Connection) -> None:
    token = verified_session(client, *PRIYA)
    code = client.post("/sessions/step-up", headers=auth(token)).json()["demo_code"]

    row = db.execute("select otp_hash from sessions where token = %s", (token,)).fetchone()

    assert row is not None and row[0].startswith("$2")  # a bcrypt hash
    assert code not in row[0]


def test_step_up_needs_a_pin_first(client: TestClient) -> None:
    token = start_session(client)

    response = client.post("/sessions/step-up", headers=auth(token))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "verification_required"


def test_two_transfers_at_once_cannot_both_overdraw(db: psycopg.Connection) -> None:
    """Sam has $3,100 in savings. Two $2,000 transfers race: only one may win.

    The first holds the customer lock; the second waits, then sees the new
    balance and is refused.
    """
    row = db.execute("select id from customers where customer_code = 'C-1004'").fetchone()
    assert row is not None
    sam_id = row[0]
    ids = dict(
        db.execute("select last4, id from accounts where customer_id = %s", (sam_id,)).fetchall()
    )
    now = datetime.now(UTC)
    session_row = db.execute(
        "insert into sessions (customer_id, token, verified, step_up_verified, expires_at) "
        "values (%s, %s, true, true, %s) returning id",
        (sam_id, "race-test", now + timedelta(minutes=10)),
    ).fetchone()
    assert session_row is not None
    session = Session(
        session_row[0], sam_id, "race-test", True, True, now, now + timedelta(minutes=10)
    )
    limits = TransferLimits(
        per_transfer_cents=250_000,
        daily_cents=500_000,
        step_up_threshold_cents=100_000,
        timezone=ZoneInfo(settings.bank_timezone),
    )

    def service_on(conn: psycopg.Connection) -> TransferService:
        return TransferService(
            transfers=TransferRepository(conn),
            accounts=AccountRepository(conn),
            audit=AuditRepository(conn),
            limits=limits,
        )

    def attempt(service: TransferService) -> Any:
        return service.transfer(
            session,
            from_account_id=ids["2209"],
            to_account_id=ids["1148"],
            amount_cents=200_000,
            idempotency_key=str(uuid4()),
        )

    result: dict[str, Any] = {}
    with (
        psycopg.connect(settings.database_url) as first,
        psycopg.connect(settings.database_url) as second,
    ):
        attempt(service_on(first))  # holds the lock, not committed yet

        def second_attempt() -> None:
            try:
                result["second"] = attempt(service_on(second))
            except BankRefusal as error:
                result["second"] = error.code
            second.commit()

        thread = threading.Thread(target=second_attempt)
        thread.start()
        thread.join(timeout=0.5)
        assert thread.is_alive(), "the second transfer should be waiting for the lock"
        first.commit()
        thread.join(timeout=5)

    assert result["second"] == "insufficient_funds"
    assert balances(db)["2209"] == 110_000


def test_a_crash_mid_transfer_moves_no_money(
    db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The money moves, then something crashes before the request finishes.
    Everything must roll back: no half-finished transfer is ever saved."""
    original = TransferRepository.execute

    def execute_then_crash(self: TransferRepository, **kwargs: Any) -> Any:
        original(self, **kwargs)
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(TransferRepository, "execute", execute_then_crash)
    before = balances(db)

    with TestClient(app, raise_server_exceptions=False) as crashing_client:
        token = verified_session(crashing_client, *PRIYA)
        ids = account_ids(crashing_client, token)
        response = send(crashing_client, token, ids["4821"], ids["7710"], 20_000)

    assert response.status_code == 500
    assert balances(db) == before
    assert db.execute("select count(*) from transfers").fetchone() == (0,)


def test_transfers_are_audited(client: TestClient, db: psycopg.Connection) -> None:
    token = verified_session(client, *SAM)
    ids = account_ids(client, token)
    send(client, token, ids["2209"], ids["1148"], 1_000)
    send(client, token, ids["1148"], ids["2209"], 999_999)

    rows = db.execute(
        "select outcome, details->>'reason' from audit_log "
        "where action = 'transfer.create' order by id"
    ).fetchall()
    assert rows == [("allowed", None), ("denied", "per_transfer_limit")]
