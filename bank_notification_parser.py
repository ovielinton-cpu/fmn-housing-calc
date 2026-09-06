"""
Turns a raw captured notification (package name + title + body text) into a
normalized transaction dict, or None if it doesn't look like a transaction
alert at all.

Nigerian banks/fintechs each phrase their alerts a bit differently, and they
change wording over time, so this ships with:
  1. A generic best-effort parser that works reasonably well across most of
     them by looking for currency amounts and credit/debit keywords.
  2. An optional per-package override table (BANK_PATTERNS) you fill in as
     you see real examples from your own banking apps' notifications, for
     the cases the generic parser gets wrong.

Nothing here is hardcoded to a specific bank's package name — you add those
yourself once you know them (see README "Learning mode").
"""
import re
from dataclasses import dataclass, asdict
from typing import Optional

CREDIT_WORDS = ("credited", "received", "credit alert", "inflow", "deposit")
DEBIT_WORDS = ("debited", "debit alert", "purchase", "withdrawal", "transfer to",
               "spent", "payment of", "sent")

AMOUNT_RE = re.compile(r"(?:NGN|N|₦)\s?([\d]{1,3}(?:,\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE)
BALANCE_RE = re.compile(r"bal(?:ance)?\.?\s*(?:is|:)?\s*(?:NGN|N|₦)?\s?([\d]{1,3}(?:,\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE)
FROM_RE = re.compile(r"\bfrom\s+([A-Za-z0-9 .'\-]{2,40})", re.IGNORECASE)
TO_RE = re.compile(r"\bto\s+([A-Za-z0-9 .'\-]{2,40})", re.IGNORECASE)


@dataclass
class Transaction:
    package: str
    direction: str          # "credit", "debit", or "unknown"
    amount: Optional[float]
    currency: str
    counterparty: Optional[str]
    balance_after: Optional[float]
    raw_text: str
    posted_at: int

    def to_dict(self):
        return asdict(self)


# Fill this in as you learn each bank/fintech's exact wording. Example shape:
#
# BANK_PATTERNS = {
#     "com.gtbank.gtworld": {
#         "amount": re.compile(r"...your own pattern..."),
#     },
# }
BANK_PATTERNS: dict = {}


def _parse_amount(text: str) -> Optional[float]:
    m = AMOUNT_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def _parse_balance(text: str) -> Optional[float]:
    m = BALANCE_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def _parse_direction(text: str) -> str:
    lowered = text.lower()
    if any(w in lowered for w in CREDIT_WORDS):
        return "credit"
    if any(w in lowered for w in DEBIT_WORDS):
        return "debit"
    return "unknown"


def _parse_counterparty(text: str, direction: str) -> Optional[str]:
    pattern = FROM_RE if direction == "credit" else TO_RE
    m = pattern.search(text)
    if m:
        return m.group(1).strip().rstrip(".")
    # fall back to trying the other direction's wording
    m = (TO_RE if pattern is FROM_RE else FROM_RE).search(text)
    return m.group(1).strip().rstrip(".") if m else None


def parse(package: str, title: str, text: str, posted_at: int) -> Optional[Transaction]:
    """Returns a Transaction if this looks like a money-movement alert, else None."""
    combined = f"{title} {text}".strip()
    if not combined:
        return None

    amount = _parse_amount(combined)
    direction = _parse_direction(combined)

    # If we can't find an amount AND can't tell the direction, this almost
    # certainly isn't a transaction alert (promo, OTP, login alert, etc.) —
    # skip it rather than record garbage.
    if amount is None and direction == "unknown":
        return None

    override = BANK_PATTERNS.get(package, {})
    if "amount" in override:
        m = override["amount"].search(combined)
        if m:
            amount = float(m.group(1).replace(",", ""))

    return Transaction(
        package=package,
        direction=direction,
        amount=amount,
        currency="NGN",
        counterparty=_parse_counterparty(combined, direction),
        balance_after=_parse_balance(combined),
        raw_text=combined,
        posted_at=posted_at,
    )
