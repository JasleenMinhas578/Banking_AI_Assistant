"""Text chat with the agent in your terminal: `make chat`.

This script plays the gateway's part until phase 7 builds the real one:
it starts the bank session, and when the agent pauses for a PIN or a
one-time code, it reads it with hidden input and sends it straight to the
bank API. The agent only ever learns whether it worked.
"""

import asyncio
import getpass
import uuid
from typing import Any

import httpx2

from app.agent import Agent, AgentOutput
from app.config import Settings, settings
from app.graph import build_graph

PROFILES = [
    ("Priya Sharma", "C-1001", "2468", "healthy balances"),
    ("Marcus Lee", "C-1002", "1357", "lost card"),
    ("Elena Rossi", "C-1003", "8642", "suspicious charge"),
    ("Sam Okafor", "C-1004", "9753", "low balance"),
    ("The impostor", "C-9999", "", "no PIN, try to break in"),
]


class BankGateway:
    """The gateway's own calls to the bank API: sessions, PIN and one-time codes."""

    def __init__(self, http: httpx2.AsyncClient) -> None:
        self.http = http
        self.token = ""

    async def start_session(self) -> str:
        response = await self.http.post("/sessions")
        response.raise_for_status()
        self.token = str(response.json()["session_token"])
        return self.token

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def verify_pin(self, customer_code: str, pin: str) -> dict[str, Any]:
        response = await self.http.post(
            "/sessions/verify",
            headers=self._auth(),
            json={"customer_code": customer_code, "pin": pin},
        )
        code = _error_code(response)
        return {
            "verified": response.status_code == 200,
            "locked": code == "account_locked",
            "customer_code": customer_code if response.status_code == 200 else None,
        }

    async def send_code(self) -> str | None:
        """Ask the bank for a one-time code. In demo mode the bank returns it."""
        response = await self.http.post("/sessions/step-up", headers=self._auth())
        return response.json().get("demo_code") if response.status_code == 200 else None

    async def verify_code(self, code: str) -> dict[str, Any]:
        response = await self.http.post(
            "/sessions/step-up/verify", headers=self._auth(), json={"code": code}
        )
        return {
            "verified": response.status_code == 200,
            "exhausted": _error_code(response) in {"otp_attempts_exhausted", "otp_expired"},
        }


def _error_code(response: Any) -> str | None:
    try:
        return str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None


def pick_profile() -> tuple[str, str, str]:
    print("\nPuffin Bank demo. Who's calling?")
    for number, (name, code, pin, story) in enumerate(PROFILES, start=1):
        hint = f"PIN {pin}" if pin else "no PIN"
        print(f"  {number}. {name} ({code}, {hint}) – {story}")
    while True:
        choice = input("Pick 1-5: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(PROFILES):
            name, code, pin, _ = PROFILES[int(choice) - 1]
            return name, code, pin


async def handle_pause(
    output: AgentOutput, agent: Agent, bank: BankGateway, code: str
) -> AgentOutput:
    """Deal with the agent's pauses until it has a reply."""
    while output.kind != "reply":
        print(f"\nPuffin: {output.text}")
        if output.kind == "pin":
            pin = getpass.getpass("  [keypad, hidden] PIN (blank to cancel): ").strip()
            outcome = await bank.verify_pin(code, pin) if pin else {"cancelled": True}
            output = await agent.answer(outcome)
        elif output.kind == "one_time_code":
            demo_code = await bank.send_code()
            if demo_code:
                print(f"  [demo phone] Your Puffin Bank code is {demo_code}")
            entered = getpass.getpass("  [keypad, hidden] Code (blank to cancel): ").strip()
            outcome = await bank.verify_code(entered) if entered else {"cancelled": True}
            output = await agent.answer(outcome)
        else:  # confirm
            output = await agent.answer(input("You: "))
    return output


async def chat(config: Settings) -> None:
    name, customer_code, _ = pick_profile()
    graph = build_graph(config)
    async with httpx2.AsyncClient(base_url=config.bank_api_url, timeout=10) as http:
        bank = BankGateway(http)
        token = await bank.start_session()
        agent = Agent(
            graph,
            call_id=str(uuid.uuid4()),
            session_token=token,
            recursion_limit=config.recursion_limit,
        )
        print(f"\nPuffin: Hi, thanks for calling Puffin Bank. How can I help? (calling as {name})")
        print("        (type 'quit' to hang up)")
        while True:
            text = input("\nYou: ").strip()
            if text.lower() in {"quit", "exit", "bye"}:
                print("Puffin: Thanks for calling. Goodbye!")
                return
            if not text:
                continue
            output = await handle_pause(await agent.say(text), agent, bank, customer_code)
            print(f"\nPuffin: {output.text}")
            if output.ended:
                return


def main() -> None:
    try:
        asyncio.run(chat(settings))
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
