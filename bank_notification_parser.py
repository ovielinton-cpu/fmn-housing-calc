"""
Turns a raw captured notification (package name + title + body text) into a
normalized transaction dict, or None if it doesn't look like a transaction
alert at all.

Tuned against real UBA and FCMB SMS debit/credit alerts, e.g.:

  UBA:
    Txn:DR
    Ac:2XX..26X
    Amt:NGN 10,200.00
    Des:POS Trf @ 22140HLY-OPay Chidex Obi Venture Ajerom
    Date:17-09-2026 08:35
    Bal:NGN 13,289.77

  FCMB:
    Dr Amt:NGN100,000.00
    AC: **4012
    DESC: |SMB1226657512|RPMT-FAST
    DT:11/09/26 18:22
    BAL:NGN37,675.21

Both banks label the amount as "Amt:" and mark direction either as a
separate "Txn:DR/CR" field (UBA) or attached directly to the amount as
"Dr Amt:"/"Cr Amt:" (FCMB) — so those two patterns are checked first, with
the older generic keyword-based guessing kept as a fallback for any other
bank/fintech that shows up later with an unrecognized format.
"""
import re
from dataclasses import dataclass, asdict
from typing import Optional

# --- Generic fallback vocabulary (used only if neither bank-specific
# pattern below matches) ---
CREDIT_WORDS = ("credited", "received", "credit alert", "inflow", "deposit")
DEBIT_WORDS = ("debited", "debit alert", "purchase", "withdrawal", "transfer to",
               "spent", "payment of", "sent")
GENERIC_AMOUNT_RE = re.compile(r"(?:NGN|N|₦)\s?([\d]{1,3}(?:,\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE)

# --- UBA-style: "Txn:DR" / "Txn:CR" as its own field ---
UBA_TXN_TYPE_RE = re.compile(r"Txn\s*:\s*(DR|CR)\b", re.IGNORECASE)

# --- FCMB-style: direction attached directly to the amount label ---
FCMB_TXN_TYPE_RE = re.compile(r"\b(Dr|Cr)\s*Amt\s*:", re.IGNORECASE)

# --- Shared across both: amount always follows "Amt:", balance always
# follows "Bal:"/"BAL:" ---
AMOUNT_AFTER_AMT_RE = re.compile(r"Amt\s*:\s*(?:NGN|N|₦)?\s*([\d]{1,3}(?:,\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE)
BALANCE_RE = re.compile(r"\bBal(?:ance)?\s*:?\s*(?:NGN|N|₦)?\s*([\d]{1,3}(?:,\d{3})*(?:\.\d{1,2})?)", re.IGNORECASE)

# --- Narration: "Des:"/"DESC:" up to the next known field label ---
NARRATION_RE = re.compile(
    r"Des(?:c)?\s*:\s*(.*?)(?:\s*(?:Date|DT|Bal|BAL)\s*:|$)",
    re.IGNORECASE | re.DOTALL,
)

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


# Optional per-package overrides for anything a future bank's format needs
# handled completely differently from everything above.
BANK_PATTERNS: dict = {}


def _to_float(num_str: str) -> float:
    return float(num_str.replace(",", ""))


def _parse_direction(text: str) -> str:
    m = UBA_TXN_TYPE_RE.search(text)
    if m:
        return "credit" if m.group(1).upper() == "CR" else "debit"

    m = FCMB_TXN_TYPE_RE.search(text)
    if m:
        return "credit" if m.group(1).upper() == "CR" else "debit"

    lowered = text.lower()
    if any(w in lowered for w in CREDIT_WORDS):
        return "credit"
    if any(w in lowered for w in DEBIT_WORDS):
        return "debit"
    return "unknown"


def _parse_amount(text: str) -> Optional[float]:
    m = AMOUNT_AFTER_AMT_RE.search(text)
    if m:
        return _to_float(m.group(1))
    m = GENERIC_AMOUNT_RE.search(text)
    return _to_float(m.group(1)) if m else None


def _parse_balance(text: str) -> Optional[float]:
    m = BALANCE_RE.search(text)
    return _to_float(m.group(1)) if m else None


def _parse_narration(text: str, direction: str) -> Optional[str]:
    m = NARRATION_RE.search(text)
    if m:
        narration = m.group(1).strip().strip("|").strip()
        if narration:
            return narration[:80]

    # Fallback for other banks' plain-English wording, e.g. "from JOHN DOE"
    pattern = FROM_RE if direction == "credit" else TO_RE
    m = pattern.search(text)
    if m:
        return m.group(1).strip().rstrip(".")
    m = (TO_RE if pattern is FROM_RE else FROM_RE).search(text)
    return m.group(1).strip().rstrip(".") if m else None


def parse(package: str, title: str, text: str, posted_at: int) -> Optional[Transaction]:
    """Returns a Transaction if this looks like a money-movement alert, else None."""
    combined = f"{title} {text}".strip()
    if not combined:
        return None

    direction = _parse_direction(combined)
    amount = _parse_amount(combined)

    # If we can't find an amount AND can't tell the direction, this almost
    # certainly isn't a transaction alert (promo, OTP, login alert, etc.) —
    # skip it rather than record garbage.
    if amount is None and direction == "unknown":
        return None

    override = BANK_PATTERNS.get(package, {})
    if "amount" in override:
        m = override["amount"].search(combined)
        if m:
            amount = _to_float(m.group(1))

    return Transaction(
        package=package,
        direction=direction,
        amount=amount,
        currency="NGN",
        counterparty=_parse_narration(combined, direction),
        balance_after=_parse_balance(combined),
        raw_text=combined,
        posted_at=posted_at,
    )
