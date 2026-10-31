"""Live calls: an Agent plus its bank session, by call id."""

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx2
from langgraph.graph.state import CompiledStateGraph

from app.agent import Agent, AgentOutput
from app.chat import PROFILES, BankGateway
from app.config import Settings
from app.graph import build_graph
from app.tracing import Tracer

GREETING = "Hi, thanks for calling Puffin Bank. How can I help?"


@dataclass
class Call:
    call_id: str
    customer_code: str
    name: str
    agent: Agent
    bank: BankGateway
    transcript: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Turn:
    kind: str  # reply | pin | one_time_code | confirm
    text: str
    ended: bool = False
    handoff_reason: str | None = None
    demo_code: str | None = None  # the one-time code, in demo mode only
    trace: dict[str, Any] | None = None
    heard: str | None = None  # what speech-to-text understood, when audio came in


class CallStore:
    def __init__(self, config: Settings, http: httpx2.AsyncClient) -> None:
        self.config = config
        self.http = http
        self.tracer = Tracer(config.trace_path)
        self.graph: CompiledStateGraph = build_graph(config, tracer=self.tracer)
        self.calls: dict[str, Call] = {}

    async def start(self, customer_code: str) -> Call:
        profile = next((p for p in PROFILES if p[1] == customer_code), None)
        if profile is None:
            raise KeyError(customer_code)
        bank = BankGateway(self.http)
        token = await bank.start_session()
        call_id = str(uuid.uuid4())
        agent = Agent(
            self.graph,
            call_id=call_id,
            session_token=token,
            recursion_limit=self.config.recursion_limit,
        )
        call = Call(call_id, customer_code, profile[0], agent, bank)
        call.transcript.append({"role": "assistant", "text": GREETING})
        self.calls[call_id] = call
        return call

    def get(self, call_id: str) -> Call:
        return self.calls[call_id]

    async def say(self, call: Call, text: str, heard: str | None = None) -> Turn:
        call.transcript.append({"role": "caller", "text": text})
        return await self._finish(call, await call.agent.say(text), heard)

    async def pin(self, call: Call, pin: str) -> Turn:
        outcome = (
            await call.bank.verify_pin(call.customer_code, pin) if pin else {"cancelled": True}
        )
        call.transcript.append(
            {"role": "caller", "text": "[PIN entered]" if pin else "[cancelled]"}
        )
        return await self._finish(call, await call.agent.answer(outcome))

    async def code(self, call: Call, code: str) -> Turn:
        outcome = await call.bank.verify_code(code) if code else {"cancelled": True}
        call.transcript.append(
            {"role": "caller", "text": "[code entered]" if code else "[cancelled]"}
        )
        return await self._finish(call, await call.agent.answer(outcome))

    async def confirm(self, call: Call, text: str) -> Turn:
        call.transcript.append({"role": "caller", "text": text})
        return await self._finish(call, await call.agent.answer(text))

    async def _finish(self, call: Call, output: AgentOutput, heard: str | None = None) -> Turn:
        demo_code = None
        if output.kind == "one_time_code":
            demo_code = await call.bank.send_code()  # the bank "texts" it; demo mode returns it
        call.transcript.append({"role": "assistant", "text": output.text})
        trace = self.tracer.last_turn.get(call.call_id) if output.kind == "reply" else None
        if output.ended:
            self.calls.pop(call.call_id, None)
        return Turn(
            output.kind, output.text, output.ended, output.handoff_reason, demo_code, trace, heard
        )
