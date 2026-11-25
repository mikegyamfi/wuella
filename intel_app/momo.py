"""
Mobile Money SMS parsing for the MacroDroid top-up gateway.

Pure Python on purpose (no Django imports) so it can be unit-tested in isolation.
See MACRODROID_MOMO_INTEGRATION.md section 6 for the reasoning behind every rule here.
"""
import re
from decimal import Decimal, InvalidOperation

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

# The amount is anchored to the START of the message, so a forged amount later in
# the body (inside the reference or sender name, which the payer controls) or the
# account balance can never be read as the amount. Accepts "1,250.00" and "1250.00".
_AMOUNT_RE = re.compile(
    r"^(?:Payment received for|You have received)\s*(?:GHS|GHC|GH₵)\s*"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

# The Transaction ID must be IMMEDIATELY followed by the fee suffix the telco itself
# appends. The payer cannot put text after that suffix, so the LAST match is the
# real telco ID even if a fake "Transaction ID: ... TRANSACTION FEE" was injected
# into the reference field.
_TXN_ID_RE = re.compile(
    r"(?:Financial Transaction Id|Transaction ID):\s*(\d{6,20})\.?\s*"
    r"(?:TRANSACTION FEE|Fee charged)",
    re.IGNORECASE,
)

_WHITESPACE_RE = re.compile(r"\s+")
_SENDER_STRIP_RE = re.compile(r"[\s\-_]")


def parse_momo_sms(sms_body):
    """
    Parse a Ghana MTN MoMo payment confirmation SMS.

    Returns ``(transaction_id, amount)``:
      * ``transaction_id`` is a ``str`` or ``None``. ``None`` means "not a payment
        confirmation" (OTP, promo, balance enquiry...). Callers store it as Ignored.
      * ``amount`` is a ``Decimal`` with 2 places. ``Decimal('0.00')`` means the
        amount could not be read. Callers must treat that as NOT claimable, never
        as a 0-cedi payment.
    """
    if not sms_body:
        return None, ZERO

    # Collapse line breaks / repeated spaces so multi-line SMS parse like one-liners.
    body = _WHITESPACE_RE.sub(" ", str(sms_body)).strip()

    amount = ZERO
    amount_match = _AMOUNT_RE.search(body)
    if amount_match:
        try:
            amount = Decimal(amount_match.group(1).replace(",", "")).quantize(CENT)
        except InvalidOperation:
            amount = ZERO

    id_matches = _TXN_ID_RE.findall(body)
    txn_id = id_matches[-1] if id_matches else None

    return txn_id, amount


def normalise_momo_sender(sender):
    """Lower-case and drop spaces/dashes/underscores: 'Mobile Money' == 'MobileMoney'."""
    return _SENDER_STRIP_RE.sub("", str(sender or "")).lower()


def normalise_txn_id(value):
    """
    Clean a Transaction ID typed/pasted by a customer.

    Customers paste things like " 73958990227 ", "ID: 73958990227." or
    "7395 8990 227". MoMo IDs are digits only, so keep only digits.
    Returns '' when nothing usable is left.
    """
    digits = re.sub(r"\D", "", str(value or ""))
    if not 6 <= len(digits) <= 20:
        return ""
    return digits
