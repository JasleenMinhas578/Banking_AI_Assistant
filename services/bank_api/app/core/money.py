"""Money helpers. Money is always whole cents (int), never a float."""


def format_cents(cents: int) -> str:
    """Turn cents into a display string: 324050 -> '$3,240.50', -18432 -> '-$184.32'."""
    sign = "-" if cents < 0 else ""
    dollars, remainder = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{remainder:02d}"


def mask_last4(last4: str) -> str:
    """Show only the last four digits: '4821' -> '••••4821'."""
    return f"••••{last4}"
