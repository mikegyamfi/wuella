"""
Manual Mobile Money wallet top-ups via the MacroDroid SMS gateway.

  * momo_webhook  - called by the Android phone (MacroDroid) for every MoMo SMS.
  * momo_claim    - the customer pastes the Transaction ID from their SMS and
                    gets credited exactly the amount the telco SMS shows.

Spec: MACRODROID_MOMO_INTEGRATION.md. Invariants I1-I12 in section 3 are enforced here.
"""
import hmac
import ipaddress
import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from intel_app import models
from intel_app.momo import normalise_momo_sender, normalise_txn_id, parse_momo_sms

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")
MIN_SECRET_LENGTH = 32
MAX_SMS_LENGTH = 2000
MAX_BODY_BYTES = 16 * 1024

Alert = models.MobileMoneyAlert


# ---------------------------------------------------------------------------
# Webhook (phone -> server)
# ---------------------------------------------------------------------------

def _secret_is_valid(request):
    expected = getattr(settings, "MACRODROID_SECRET", "") or ""
    min_length = max(int(getattr(settings, "MACRODROID_MIN_SECRET_LENGTH", MIN_SECRET_LENGTH) or 0), 12)
    if len(expected) < min_length:
        logger.error("MACRODROID_SECRET is missing or shorter than %s chars; rejecting MoMo webhook.",
                     min_length)
        return False
    supplied = request.headers.get("X-Secret-Key") or ""
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def _read_payload(request):
    """
    Accept a JSON body (recommended) or a form-encoded body.
    Returns a dict, or None when the body can't be read.
    """
    content_type = (request.content_type or "").lower()
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        return request.POST.dict()
    try:
        # strict=False: MacroDroid pastes the SMS straight into the JSON template, so a
        # multi-line SMS arrives with raw line breaks inside the string. Accept them.
        data = json.loads(request.body.decode("utf-8"), strict=False)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _allowed_senders():
    return {normalise_momo_sender(s) for s in getattr(settings, "MOMO_ALLOWED_SENDERS", ["MobileMoney"])}


@csrf_exempt
def momo_webhook(request):
    """
    POST /momo/webhook/
    Header: X-Secret-Key: <MACRODROID_SECRET>
    Body:   {"sms_body": "...", "sender": "MobileMoney", "timestamp": "..."}

    200 {"status": "success", "id": "<txn>"}        new claimable alert stored
    200 {"status": "duplicate", ...}                 already stored (safe MacroDroid retry)
    200 {"status": "ignored", "reason": "..."}       stored as Ignored, never claimable
    400 invalid body | 403 bad secret | 405 not POST | 413 too large | 500 unexpected error
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    if not _secret_is_valid(request):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    if len(request.body) > MAX_BODY_BYTES:
        return JsonResponse({"error": "Payload too large"}, status=413)

    data = _read_payload(request)
    if data is None:
        logger.warning("MoMo webhook received an unreadable body (first 300 bytes): %r", request.body[:300])
        return JsonResponse({"error": "invalid json"}, status=400)

    try:
        sms_body = str(data.get("sms_body") or "")[:MAX_SMS_LENGTH]
        sender = str(data.get("sender") or "").strip()[:50]
        timestamp = str(data.get("timestamp") or "").strip()[:100]

        txn_id, amount = parse_momo_sms(sms_body)

        if normalise_momo_sender(sender) not in _allowed_senders():
            # Anyone can text the gateway phone a fake "Payment received..." SMS.
            reason = "Sender not allowed"
        elif not txn_id:
            reason = "No ID found"
        elif amount <= ZERO:
            # Looks like a payment but the amount is unreadable. Never let it be
            # claimed for 0 (that would use up the customer's real payment).
            reason = "Amount unreadable"
        else:
            reason = None

        if reason:
            # No transaction_id stored: can never be claimed and never blocks a real row.
            Alert.objects.create(
                raw_sms_body=sms_body,
                sender_address=sender,
                received_at_phone=timestamp,
                status=Alert.STATUS_IGNORED,
                ignore_reason=reason,
            )
            if reason != "No ID found":
                logger.warning("MoMo webhook ignored SMS (%s) from sender %r, parsed id %r",
                               reason, sender, txn_id)
            return JsonResponse({"status": "ignored", "reason": reason})

        # Idempotent insert: unique transaction_id + get_or_create (which itself
        # recovers from the IntegrityError of a concurrent duplicate insert).
        with db_transaction.atomic():
            alert, created = Alert.objects.get_or_create(
                transaction_id=txn_id,
                defaults={
                    "raw_sms_body": sms_body,
                    "sender_address": sender,
                    "received_at_phone": timestamp,
                    "amount": amount,
                    "status": Alert.STATUS_UNCLAIMED,
                },
            )

        if not created:
            if alert.amount != amount:
                logger.warning("MoMo duplicate for txn %s with a DIFFERENT amount (stored %s, new %s). "
                               "Stored row kept.", txn_id, alert.amount, amount)
            return JsonResponse({"status": "duplicate", "message": "Already received"})

        logger.info("MoMo alert stored: txn %s, GHS %s", txn_id, amount)
        return JsonResponse({"status": "success", "id": txn_id})

    except Exception:
        logger.exception("MoMo webhook error")
        return JsonResponse({"error": "Server error"}, status=500)


# ---------------------------------------------------------------------------
# Claim (customer -> server)
# ---------------------------------------------------------------------------

def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    candidate = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _recent_failed_claims(user):
    since = timezone.now() - timedelta(hours=1)
    return models.MoMoClaimAttempt.objects.filter(user=user, successful=False, created_at__gte=since).count()


def _record_attempt(request, topup, txn_id, outcome, successful=False):
    models.MoMoClaimAttempt.objects.create(
        user=request.user,
        topup_request=topup,
        entered_transaction_id=txn_id[:100],
        successful=successful,
        outcome=outcome[:100],
        ip_address=_client_ip(request),
    )


def _claim_window():
    hours = int(getattr(settings, "MOMO_CLAIM_WINDOW_HOURS", 0) or 0)
    return timedelta(hours=hours) if hours > 0 else None


@login_required(login_url='login')
def momo_claim(request, reference):
    topup = get_object_or_404(models.TopUpRequest, reference=reference, user=request.user)

    if request.method == "POST":
        return _process_claim(request, topup)

    admin_info = models.AdminInfo.objects.first()
    momo_number = getattr(admin_info, "momo_number", None)
    context = {
        "topup": topup,
        "momo_number": f"0{momo_number}" if momo_number else "",
        "momo_name": getattr(admin_info, "name", "") or "",
        "momo_channel": getattr(admin_info, "payment_channel", "") or "MTN Mobile Money",
        "claim_window_hours": int(getattr(settings, "MOMO_CLAIM_WINDOW_HOURS", 0) or 0),
    }
    return render(request, "layouts/services/momo_claim.html", context)


def _process_claim(request, topup):
    retry = redirect("momo_claim", reference=topup.reference)
    raw_input = (request.POST.get("transaction_id") or "").strip()
    txn_id = normalise_txn_id(raw_input)

    if not txn_id:
        messages.error(request, "Please enter the Transaction ID (digits only) from your MoMo SMS.")
        return retry

    max_failed = int(getattr(settings, "MOMO_MAX_FAILED_CLAIMS_PER_HOUR", 8) or 8)
    if _recent_failed_claims(request.user) >= max_failed:
        logger.warning("MoMo claim rate limit hit by user %s (last input %r)", request.user.pk, raw_input)
        messages.error(request, "Too many failed attempts. Please wait an hour or contact support.")
        return retry

    try:
        with db_transaction.atomic():
            # Lock the top-up row so a double submit cannot complete it twice.
            topup = models.TopUpRequest.objects.select_for_update().get(pk=topup.pk)
            if topup.status:
                messages.info(request, "This top-up request has already been completed.")
                return redirect("home")

            # Lock the alert row: stops two users / two tabs claiming the same SMS.
            alert = Alert.objects.select_for_update().filter(transaction_id=txn_id).first()

            if alert is None:
                _record_attempt(request, topup, txn_id, "not found")
                messages.error(request, "Transaction ID not found. If you just paid, wait a minute "
                                        "and try again. Make sure you paid to the number shown.")
                return retry

            if alert.status == Alert.STATUS_CLAIMED:
                _record_attempt(request, topup, txn_id, "already claimed")
                messages.error(request, "This Transaction ID has already been used.")
                return retry

            if alert.status != Alert.STATUS_UNCLAIMED or alert.amount is None or alert.amount <= ZERO:
                _record_attempt(request, topup, txn_id, f"not claimable ({alert.status})")
                messages.error(request, "This transaction cannot be claimed. Please contact support.")
                return retry

            window = _claim_window()
            if window and timezone.now() - alert.created_at > window:
                alert.status = Alert.STATUS_EXPIRED
                alert.save(update_fields=["status"])
                _record_attempt(request, topup, txn_id, "expired")
                messages.error(request, "This transaction is too old to claim online. Please contact support.")
                return retry

            # Lock the wallet row. refresh_from_db() would not stop a concurrent debit
            # from overwriting this credit (or vice versa).
            user = models.CustomUser.objects.select_for_update().get(pk=request.user.pk)
            now = timezone.now()
            amount = alert.amount
            requested_amount = topup.amount

            # Flip the alert FIRST; any later failure rolls the whole block back.
            alert.status = Alert.STATUS_CLAIMED
            alert.claimed_by = user
            alert.claimed_at = now
            alert.topup_request = topup
            alert.save(update_fields=["status", "claimed_by", "claimed_at", "topup_request"])

            # Credit EXACTLY what the telco SMS says, not what was requested.
            user.wallet = (user.wallet or ZERO) + amount
            user.save(update_fields=["wallet"])

            topup.amount = amount
            topup.status = True
            topup.credited_at = now
            topup.save(update_fields=["amount", "status", "credited_at"])

            models.Payment.objects.create(
                user=user,
                reference=f"MOMO-{txn_id}",
                amount=amount,
                payment_description="Wallet top-up via manual MoMo (SMS gateway)",
                transaction_status="Success",
                transaction_date=now.isoformat(),
                message=(f"Top-up ref {topup.reference}; requested GHS {requested_amount}; "
                         f"credited GHS {amount}; new balance GHS {user.wallet}")[:500],
            )

            _record_attempt(request, topup, txn_id, "claimed", successful=True)

    except Exception:
        logger.exception("MoMo claim failed for user %s, top-up %s, txn %s",
                         request.user.pk, topup.reference, txn_id)
        messages.error(request, "System error processing your claim. Please try again or contact support.")
        return retry

    logger.info("MoMo txn %s claimed by user %s: GHS %s", txn_id, request.user.pk, amount)
    messages.success(request, f"Success! GHS {amount:,.2f} has been added to your wallet.")
    return redirect("home")
