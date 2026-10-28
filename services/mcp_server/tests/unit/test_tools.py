"""Every tool's logic against a fake bank: masking, references, errors, two-step transfers."""

from datetime import UTC, datetime, timedelta

import pytest

from app.bank_client import BankApiError
from app.refs import RefRegistry
from app.tools import BankTools, ToolFailure
from tests.unit.fake_bank import CARD, CHEQUING, COSTCO, SAVINGS, TOKEN, FakeBank

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def bank() -> FakeBank:
    return FakeBank()


@pytest.fixture
def tools(bank: FakeBank, clock: Clock) -> BankTools:
    return BankTools(
        bank=bank,
        registry=RefRegistry(timedelta(minutes=30), clock),
        quote_ttl=timedelta(minutes=5),
        step_up_threshold_cents=100_000,
        clock=clock,
    )


async def test_accounts_come_back_masked_with_short_refs(tools: BankTools) -> None:
    result = await tools.get_accounts(TOKEN)

    assert [(a.ref, a.type, a.number, a.balance) for a in result.accounts] == [
        ("A1", "chequing", "••••4821", "$3,240.50"),
        ("A2", "savings", "••••7710", "$12,500.00"),
    ]


async def test_no_real_ids_ever_reach_the_agent(tools: BankTools) -> None:
    await tools.get_accounts(TOKEN)
    outputs = [
        await tools.get_accounts(TOKEN),
        await tools.list_transactions(TOKEN, "A1", 10),
        await tools.list_cards(TOKEN),
        await tools.list_disputes(TOKEN),
    ]

    text = " ".join(o.model_dump_json() for o in outputs)
    for real_id in (CHEQUING, SAVINGS, COSTCO, CARD):
        assert str(real_id) not in text
    assert TOKEN not in text


async def test_transactions_need_an_account_ref_from_this_conversation(tools: BankTools) -> None:
    with pytest.raises(ToolFailure) as error:
        await tools.list_transactions(TOKEN, "A1", 10)

    assert error.value.code == "unknown_reference"
    assert "get_accounts" in error.value.message


async def test_transactions_get_refs_and_dates(tools: BankTools, bank: FakeBank) -> None:
    await tools.get_accounts(TOKEN)

    result = await tools.list_transactions(TOKEN, "A1", 10)

    assert [(t.ref, t.merchant, t.amount, t.date) for t in result.transactions] == [
        ("T1", "Amazon", "-$59.99", "2026-10-28"),
        ("T2", "Costco", "-$184.32", "2026-10-26"),
    ]
    assert bank.calls[-1] == ("get_transactions", (CHEQUING, 10))


async def test_freeze_card_uses_the_card_ref(tools: BankTools, bank: FakeBank) -> None:
    cards = await tools.list_cards(TOKEN)

    result = await tools.freeze_card(TOKEN, cards.cards[0].ref)

    assert result.changed is True
    assert result.card.status == "frozen"
    assert bank.calls[-1] == ("freeze_card", CARD)


async def test_cannot_freeze_with_an_account_ref(tools: BankTools) -> None:
    await tools.get_accounts(TOKEN)

    with pytest.raises(ToolFailure, match="unknown_reference"):
        await tools.freeze_card(TOKEN, "A1")


async def test_open_dispute_passes_the_reason_and_handoff(tools: BankTools) -> None:
    await tools.get_accounts(TOKEN)
    await tools.list_transactions(TOKEN, "A1", 10)

    result = await tools.open_dispute(TOKEN, "T2", "fraud")

    assert result.handoff is True
    assert result.dispute.reference == "D-11111111"
    assert result.dispute.ref == "D1"


async def test_bank_refusals_become_tool_failures_with_the_bank_code(
    tools: BankTools, bank: FakeBank
) -> None:
    bank.fail_with = BankApiError(403, "verification_required", "Please verify first.")

    with pytest.raises(ToolFailure) as error:
        await tools.get_accounts(TOKEN)

    assert (error.value.code, error.value.message) == (
        "verification_required",
        "Please verify first.",
    )


async def test_prepare_transfer_moves_nothing(tools: BankTools, bank: FakeBank) -> None:
    await tools.get_accounts(TOKEN)

    quote = await tools.prepare_transfer(TOKEN, "A1", "A2", "200")

    assert quote.quote_ref == "Q1"
    assert quote.summary == "Move $200.00 from chequing ••••4821 to savings ••••7710."
    assert quote.needs_one_time_code is False
    assert bank.balances[CHEQUING] == 324_050
    assert not any(name == "create_transfer" for name, _ in bank.calls)


async def test_confirm_moves_the_money_once_even_if_retried(
    tools: BankTools, bank: FakeBank
) -> None:
    await tools.get_accounts(TOKEN)
    quote = await tools.prepare_transfer(TOKEN, "A1", "A2", "200")

    first = await tools.confirm_transfer(TOKEN, quote.quote_ref)
    second = await tools.confirm_transfer(TOKEN, quote.quote_ref)

    assert (first.created, second.created) == (True, False)
    assert first.reference == second.reference
    assert bank.balances[CHEQUING] == 304_050
    assert first.from_account.balance == "$3,040.50"


async def test_over_1000_is_flagged_as_needing_a_code(tools: BankTools) -> None:
    await tools.get_accounts(TOKEN)

    quote = await tools.prepare_transfer(TOKEN, "A2", "A1", "1000.01")

    assert quote.needs_one_time_code is True


@pytest.mark.parametrize(
    ("source", "target", "amount", "code"),
    [
        ("A1", "A1", "10", "same_account"),
        ("A1", "A2", "ten dollars", "invalid_amount"),
        ("A1", "A2", "-5", "invalid_amount"),
        ("A1", "A2", "3240.51", "insufficient_funds"),
        ("A1", "A9", "10", "unknown_reference"),
    ],
)
async def test_prepare_transfer_refuses_bad_requests(
    tools: BankTools, source: str, target: str, amount: str, code: str
) -> None:
    await tools.get_accounts(TOKEN)

    with pytest.raises(ToolFailure) as error:
        await tools.prepare_transfer(TOKEN, source, target, amount)

    assert error.value.code == code


async def test_a_quote_expires(tools: BankTools, clock: Clock, bank: FakeBank) -> None:
    await tools.get_accounts(TOKEN)
    quote = await tools.prepare_transfer(TOKEN, "A1", "A2", "200")
    clock.now = NOW + timedelta(minutes=5)

    with pytest.raises(ToolFailure, match="quote_expired"):
        await tools.confirm_transfer(TOKEN, quote.quote_ref)

    assert bank.balances[CHEQUING] == 324_050


async def test_confirming_a_made_up_quote_is_refused(tools: BankTools) -> None:
    with pytest.raises(ToolFailure, match="unknown_reference"):
        await tools.confirm_transfer(TOKEN, "Q7")


async def test_another_caller_cannot_confirm_priyas_quote(tools: BankTools) -> None:
    await tools.get_accounts(TOKEN)
    quote = await tools.prepare_transfer(TOKEN, "A1", "A2", "200")

    with pytest.raises(ToolFailure, match="unknown_reference"):
        await tools.confirm_transfer("someone-elses-token", quote.quote_ref)
