"""What each tool returns to the agent. These become MCP structured output.

Nothing here carries a real ID, a full card or account number, a customer
name, or a session token: only short references and masked numbers.
"""

from pydantic import BaseModel, Field


class AccountView(BaseModel):
    ref: str = Field(description="Use this to refer to the account, e.g. 'A1'")
    type: str = Field(examples=["chequing"])
    number: str = Field(description="Masked, e.g. '••••4821'")
    balance: str = Field(examples=["$3,240.50"])


class AccountsResult(BaseModel):
    accounts: list[AccountView]


class TransactionView(BaseModel):
    ref: str = Field(description="Use this to dispute the transaction, e.g. 'T3'")
    merchant: str
    amount: str = Field(description="Negative means money out, e.g. '-$184.32'")
    status: str = Field(description="'posted' or 'pending'")
    date: str = Field(description="YYYY-MM-DD")


class TransactionsResult(BaseModel):
    account: AccountView
    transactions: list[TransactionView]


class CardView(BaseModel):
    ref: str = Field(description="Use this to freeze the card, e.g. 'C1'")
    number: str = Field(description="Masked, e.g. '••••4417'")
    status: str = Field(description="'active' or 'frozen'")
    account_ref: str


class CardsResult(BaseModel):
    cards: list[CardView]


class FreezeCardResult(BaseModel):
    card: CardView
    changed: bool = Field(description="False if the card was already frozen")
    message: str = Field(description="A sentence you can read to the caller")


class DisputeView(BaseModel):
    ref: str
    reference: str = Field(description="The bank's reference to read out, e.g. 'D-1A2B3C4D'")
    merchant: str
    amount: str
    reason: str
    status: str
    opened: str = Field(description="YYYY-MM-DD")


class DisputesResult(BaseModel):
    disputes: list[DisputeView]


class OpenDisputeResult(BaseModel):
    dispute: DisputeView
    created: bool = Field(description="False if a dispute was already open for this charge")
    handoff: bool = Field(description="True means a human agent must take over (fraud)")
    message: str = Field(description="A sentence you can read to the caller")


class TransferQuoteResult(BaseModel):
    quote_ref: str = Field(description="Pass this to confirm_transfer after the caller says yes")
    summary: str = Field(description="Read this back to the caller word for word")
    needs_one_time_code: bool = Field(
        description="True if the caller must enter a one-time code before confirming"
    )
    expires_in_minutes: int


class TransferResult(BaseModel):
    reference: str = Field(description="The bank's reference to read out, e.g. 'T-1A2B3C4D'")
    created: bool = Field(description="False if this transfer had already been done")
    message: str = Field(description="A sentence you can read to the caller")
    from_account: AccountView
    to_account: AccountView
