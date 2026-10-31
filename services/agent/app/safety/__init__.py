"""The moderation tiers, cheapest first. app/moderation.py chains them together.

rules.py       tier 1: regex, about a millisecond
classifier.py  tier 2: scikit-learn model trained in ml/moderation_classifier
judge.py       tier 3: Llama Guard 3 + a bank checklist on the 3B model
output.py      checks the assistant's own reply before it's spoken
"""
