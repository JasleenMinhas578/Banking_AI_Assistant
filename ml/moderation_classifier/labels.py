"""The six labels the tier-2 classifier predicts. The agent uses the same names."""

SAFE = "safe"
PROMPT_INJECTION = "prompt_injection"
SOCIAL_ENGINEERING = "social_engineering"
ABUSE = "abuse"
DISTRESS = "distress"
OFF_TOPIC = "off_topic"

LABELS = [SAFE, PROMPT_INJECTION, SOCIAL_ENGINEERING, ABUSE, DISTRESS, OFF_TOPIC]
# Must never pass as safe. Off-topic is left out: if it slips through, the router
# just answers "here's what I can help with", so it costs nothing.
HARMFUL = [PROMPT_INJECTION, SOCIAL_ENGINEERING, ABUSE, DISTRESS]
