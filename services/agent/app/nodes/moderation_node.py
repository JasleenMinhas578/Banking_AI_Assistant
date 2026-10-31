"""Moderate input: label the caller's words, then decide what happens to them.

The moderator only labels. This node owns the actions from the design doc:

    safe                continue to the router
    sensitive_data      withhold it, explain, end the turn
    prompt_injection    refuse, count a strike; at the limit, hand off
    social_engineering  explain that everyone verifies themselves
    abuse               one warning; after that, hand off
    distress            caring words and a person, straight away
    off_topic           say what the assistant can help with
"""

from typing import Any

from app.moderation import InputModerator
from app.replies import ABUSE_WARNING, INJECTION_REFUSAL, OFF_TOPIC, SOCIAL_ENGINEERING
from app.safety.rules import WITHHELD
from app.safety.types import Label, ModerationResult
from app.state import ConversationState

# Reset at the start of every turn, so nothing from the last turn leaks into this one.
FRESH_TURN: dict[str, Any] = {
    "reply": None,
    "pending_action": None,
    "confirmed": False,
    "tool_result": None,
    "handoff_reason": None,
}

BLOCK_REPLIES = {
    Label.SOCIAL_ENGINEERING: SOCIAL_ENGINEERING,
    Label.OFF_TOPIC: OFF_TOPIC,
}


class ModerationNode:
    def __init__(
        self, moderator: InputModerator, max_injection_strikes: int = 3, max_abuse_warnings: int = 1
    ) -> None:
        self.moderator = moderator
        self.max_injection_strikes = max_injection_strikes
        self.max_abuse_warnings = max_abuse_warnings

    async def run(self, state: ConversationState) -> dict[str, Any]:
        text = state.get("input", "")
        result = await self.moderator.check(text)
        update: dict[str, Any] = {
            **FRESH_TURN,
            "input": "",  # the raw text isn't kept beyond this point
            "moderation": {
                "verdict": result.verdict,
                "label": result.label.value,
                "tier": result.tier,
                "reason": result.reason,
                "score": result.score,
                "unsure": result.unsure,
            },
        }
        if result.label == Label.SAFE:
            return {**update, "messages": [{"role": "caller", "text": text}]}
        return {**update, **self._act(state, result, text)}

    def _act(self, state: ConversationState, result: ModerationResult, text: str) -> dict:
        withheld = [{"role": "caller", "text": result.safe_text or WITHHELD}]

        if result.label == Label.SENSITIVE_DATA:
            return {"messages": withheld, "reply": result.reply}

        if result.label == Label.PROMPT_INJECTION:
            strikes = state.get("injection_strikes", 0) + 1
            if strikes >= self.max_injection_strikes:
                return {
                    "messages": withheld,
                    "injection_strikes": strikes,
                    "handoff_reason": "repeated_attacks",
                }
            return {"messages": withheld, "injection_strikes": strikes, "reply": INJECTION_REFUSAL}

        if result.label == Label.ABUSE:
            strikes = state.get("abuse_strikes", 0) + 1
            if strikes > self.max_abuse_warnings:
                return {"messages": withheld, "abuse_strikes": strikes, "handoff_reason": "abuse"}
            return {"messages": withheld, "abuse_strikes": strikes, "reply": ABUSE_WARNING}

        if result.label == Label.DISTRESS:
            # Kept, so the person taking over can read what was said (digits masked there).
            return {"messages": [{"role": "caller", "text": text}], "handoff_reason": "distress"}

        return {"messages": withheld, "reply": BLOCK_REPLIES[result.label]}
