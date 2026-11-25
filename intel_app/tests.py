import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import TestCase as PlainTestCase

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from intel_app import models
from intel_app.momo import normalise_momo_sender, normalise_txn_id, parse_momo_sms

SECRET = "test-secret-" + "x" * 40

SMS_PERSONAL = ("Payment received for GHS 50.00 from JOHN DOE  Current Balance: GHS 6,500.00 . "
                "Available Balance: GHS 6,500.00. Reference: 1. Transaction ID: 70000000001. "
                "TRANSACTION FEE: 0.00")
SMS_FEE_CHARGED = ("Payment received for GHS 200.00 from AMA MENSAH (233240000000) Current Balance: "
                   "GHS 420.10 . Available Balance: GHS 420.10. Reference: data. Transaction ID: "
                   "70000000002. Fee charged: GHS0.00.")
SMS_AGENT = ("You have received GHS 500.00 from KOFI BOATENG  (233240000001) on your agent mobile money "
             "account at 2026-02-21 14:53:23. Message from sender: . Your new balance: 6300.00 GHS. "
             "Financial Transaction Id: 70000000003. TRANSACTION FEE IS 0")
SMS_THOUSANDS = ("Payment received for GHS 1,250.00 from JOHN DOE  Current Balance: GHS 9,000.00 . "
                 "Reference: 1. Transaction ID: 70000000004. TRANSACTION FEE: 0.00")
SMS_INJECTION = ("Payment received for GHS 1.00 from BAD ACTOR. "
                 "Reference: Transaction ID: 99999999 TRANSACTION FEE. "
                 "Financial Transaction Id: 12345678. TRANSACTION FEE IS GHS 0.00.")


class ParseMomoSmsTests(PlainTestCase):
    def test_standard_templates(self):
        self.assertEqual(parse_momo_sms(SMS_PERSONAL), ("70000000001", Decimal("50.00")))
        self.assertEqual(parse_momo_sms(SMS_FEE_CHARGED), ("70000000002", Decimal("200.00")))
        self.assertEqual(parse_momo_sms(SMS_AGENT), ("70000000003", Decimal("500.00")))

    def test_thousands_separator(self):
        self.assertEqual(parse_momo_sms(SMS_THOUSANDS), ("70000000004", Decimal("1250.00")))

    def test_amount_comes_from_start_not_balance(self):
        self.assertEqual(parse_momo_sms(SMS_PERSONAL)[1], Decimal("50.00"))

    def test_reference_injection_uses_real_id(self):
        self.assertEqual(parse_momo_sms(SMS_INJECTION), ("12345678", Decimal("1.00")))

    def test_multiline_sms(self):
        body = SMS_PERSONAL.replace(". ", ".\n")
        self.assertEqual(parse_momo_sms(body), ("70000000001", Decimal("50.00")))

    def test_non_payment(self):
        self.assertEqual(parse_momo_sms("Your OTP is 1234"), (None, Decimal("0.00")))
        self.assertEqual(parse_momo_sms(""), (None, Decimal("0.00")))
        self.assertEqual(parse_momo_sms(None), (None, Decimal("0.00")))

    def test_amount_unreadable(self):
        body = "Payment received from JOHN. Transaction ID: 70000000009. TRANSACTION FEE: 0.00"
        self.assertEqual(parse_momo_sms(body), ("70000000009", Decimal("0.00")))

    def test_sender_normalisation(self):
        self.assertEqual(normalise_momo_sender("Mobile Money"), "mobilemoney")
        self.assertEqual(normalise_momo_sender("mobile-money"), "mobilemoney")
        self.assertEqual(normalise_momo_sender(None), "")

    def test_txn_id_normalisation(self):
        self.assertEqual(normalise_txn_id("  73958990227 "), "73958990227")
        self.assertEqual(normalise_txn_id("ID: 7395 8990 227."), "73958990227")
        self.assertEqual(normalise_txn_id("abc"), "")
        self.assertEqual(normalise_txn_id("123"), "")


@override_settings(MACRODROID_SECRET=SECRET, MOMO_ALLOWED_SENDERS=["MobileMoney"])
class MomoWebhookTests(TestCase):
    url = "/momo/webhook/"

    def post(self, payload, secret=SECRET, raw=None):
        headers = {"HTTP_X_SECRET_KEY": secret} if secret is not None else {}
        body = raw if raw is not None else json.dumps(payload)
        return self.client.post(self.url, data=body, content_type="application/json", **headers)

    def sms(self, body, sender="MobileMoney"):
        return {"sms_body": body, "sender": sender, "timestamp": "12:00 01/01/2026"}

    def test_url_name(self):
        self.assertEqual(reverse("momo_webhook"), self.url)

    def test_auth(self):  # T1, T2
        self.assertEqual(self.post(self.sms(SMS_PERSONAL), secret=None).status_code, 403)
        self.assertEqual(self.post(self.sms(SMS_PERSONAL), secret="wrong").status_code, 403)
        self.assertFalse(models.MobileMoneyAlert.objects.exists())

    @override_settings(MACRODROID_SECRET="short")
    def test_weak_secret_rejects_everything(self):
        self.assertEqual(self.post(self.sms(SMS_PERSONAL), secret="short").status_code, 403)

    @override_settings(MACRODROID_SECRET="short-test-secret1", MACRODROID_MIN_SECRET_LENGTH=16)
    def test_short_test_secret_allowed_when_minimum_lowered(self):
        self.assertEqual(self.post(self.sms(SMS_PERSONAL), secret="short-test-secret1").status_code, 200)

    @override_settings(MACRODROID_SECRET="short-test-secret1")
    def test_short_secret_rejected_by_default(self):
        self.assertEqual(self.post(self.sms(SMS_PERSONAL), secret="short-test-secret1").status_code, 403)

    def test_get_not_allowed(self):  # T3
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_success_then_duplicate(self):  # T4, T5
        r = self.post(self.sms(SMS_PERSONAL))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "success", "id": "70000000001"})
        r = self.post(self.sms(SMS_PERSONAL))
        self.assertEqual(r.json()["status"], "duplicate")
        alert = models.MobileMoneyAlert.objects.get()
        self.assertEqual(alert.status, "Unclaimed")
        self.assertEqual(alert.amount, Decimal("50.00"))

    def test_non_payment_ignored(self):  # T6
        r = self.post(self.sms("Your OTP is 1234"))
        self.assertEqual(r.json(), {"status": "ignored", "reason": "No ID found"})
        alert = models.MobileMoneyAlert.objects.get()
        self.assertEqual(alert.status, "Ignored")
        self.assertIsNone(alert.transaction_id)

    def test_malformed_json(self):  # T7
        self.assertEqual(self.post(None, raw="{not json").status_code, 400)
        self.assertEqual(self.post(None, raw="[1, 2]").status_code, 400)

    def test_raw_newlines_in_json_accepted(self):
        # Exactly what MacroDroid's text template produces for a multi-line SMS.
        raw = '{\n  "sender": "MobileMoney",\n  "sms_body": "%s",\n  "timestamp": "1795640561476"\n}' % (
            SMS_PERSONAL.replace(". ", ".\n"))
        r = self.client.post(self.url, data=raw, content_type="text/plain", HTTP_X_SECRET_KEY=SECRET)
        self.assertEqual(r.json(), {"status": "success", "id": "70000000001"})

    def test_form_encoded_body_accepted(self):
        r = self.client.post(self.url, data=self.sms(SMS_PERSONAL), HTTP_X_SECRET_KEY=SECRET)
        self.assertEqual(r.json()["status"], "success")

    def test_wrong_sender_ignored(self):  # T21
        r = self.post(self.sms(SMS_PERSONAL, sender="+233240000000"))
        self.assertEqual(r.json(), {"status": "ignored", "reason": "Sender not allowed"})
        alert = models.MobileMoneyAlert.objects.get()
        self.assertEqual(alert.status, "Ignored")
        self.assertIsNone(alert.transaction_id)

    def test_sender_variants_accepted(self):  # T22
        self.assertEqual(self.post(self.sms(SMS_PERSONAL, sender="Mobile Money")).json()["status"], "success")
        self.assertEqual(self.post(self.sms(SMS_AGENT, sender="mobilemoney")).json()["status"], "success")

    def test_thousands_amount(self):  # T23
        self.post(self.sms(SMS_THOUSANDS))
        self.assertEqual(models.MobileMoneyAlert.objects.get().amount, Decimal("1250.00"))

    def test_unreadable_amount_ignored(self):  # T24
        body = "Payment received from JOHN. Transaction ID: 70000000009. TRANSACTION FEE: 0.00"
        r = self.post(self.sms(body))
        self.assertEqual(r.json(), {"status": "ignored", "reason": "Amount unreadable"})
        self.assertFalse(models.MobileMoneyAlert.objects.filter(transaction_id="70000000009").exists())


@override_settings(MOMO_CLAIM_WINDOW_HOURS=0, MOMO_MAX_FAILED_CLAIMS_PER_HOUR=8)
class MomoClaimTests(TestCase):
    def setUp(self):
        models.AdminInfo.objects.create(name="DANWEL STORE", momo_number=244000000,
                                        payment_channel="MTN Mobile Money", topup_method="macrodroid")
        self.user = self.make_user("alice")
        self.other = self.make_user("bob")
        self.topup = models.TopUpRequest.objects.create(user=self.user, reference="DW_TEST1", amount=Decimal("40"))
        self.alert = models.MobileMoneyAlert.objects.create(
            raw_sms_body=SMS_PERSONAL, sender_address="MobileMoney",
            transaction_id="70000000001", amount=Decimal("50.00"))
        self.client.force_login(self.user)

    def make_user(self, username):
        return models.CustomUser.objects.create_user(
            username=username, password="pw-12345-long", email=f"{username}@example.com",
            first_name=username, last_name="x", status="User", wallet=Decimal("10.00"))

    def claim(self, txn, ref="DW_TEST1", client=None):
        return (client or self.client).post(reverse("momo_claim", args=[ref]), {"transaction_id": txn})

    def test_get_renders(self):
        r = self.client.get(reverse("momo_claim", args=["DW_TEST1"]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "0244000000")

    def test_other_users_topup_404(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("momo_claim", args=["DW_TEST1"])).status_code, 404)

    def test_successful_claim_credits_sms_amount(self):  # T8, T12
        self.claim("  70000000001  ")
        self.user.refresh_from_db(); self.alert.refresh_from_db(); self.topup.refresh_from_db()
        self.assertEqual(self.user.wallet, Decimal("60.00"))  # 10 + 50 (SMS amount, not requested 40)
        self.assertEqual(self.alert.status, "Claimed")
        self.assertEqual(self.alert.claimed_by, self.user)
        self.assertEqual(self.alert.topup_request, self.topup)
        self.assertTrue(self.topup.status)
        self.assertEqual(self.topup.amount, Decimal("50.00"))
        self.assertTrue(models.Payment.objects.filter(reference="MOMO-70000000001", user=self.user).exists())

    def test_cannot_claim_twice(self):  # T9, T10
        self.claim("70000000001")
        second = models.TopUpRequest.objects.create(user=self.user, reference="DW_TEST2", amount=Decimal("50"))
        self.claim("70000000001", ref="DW_TEST2")
        other_topup = models.TopUpRequest.objects.create(user=self.other, reference="DW_BOB", amount=Decimal("50"))
        self.client.force_login(self.other)
        self.claim("70000000001", ref="DW_BOB")
        self.user.refresh_from_db(); self.other.refresh_from_db(); second.refresh_from_db(); other_topup.refresh_from_db()
        self.assertEqual(self.user.wallet, Decimal("60.00"))
        self.assertEqual(self.other.wallet, Decimal("10.00"))
        self.assertFalse(second.status)
        self.assertFalse(other_topup.status)

    def test_completed_topup_cannot_be_reused(self):
        self.claim("70000000001")
        models.MobileMoneyAlert.objects.create(raw_sms_body="x", transaction_id="70000000005", amount=Decimal("5"))
        self.claim("70000000005")  # same, already-completed top-up request
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet, Decimal("60.00"))
        self.assertEqual(models.MobileMoneyAlert.objects.get(transaction_id="70000000005").status, "Unclaimed")

    def test_not_found(self):  # T11
        self.claim("79999999999")
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet, Decimal("10.00"))
        self.assertEqual(models.MoMoClaimAttempt.objects.get().outcome, "not found")

    def test_zero_amount_and_ignored_not_claimable(self):  # T25
        models.MobileMoneyAlert.objects.create(raw_sms_body="x", transaction_id="70000000006", amount=Decimal("0"))
        models.MobileMoneyAlert.objects.create(raw_sms_body="x", transaction_id="70000000007",
                                               amount=Decimal("9"), status="Ignored")
        self.claim("70000000006")
        self.claim("70000000007")
        self.user.refresh_from_db(); self.topup.refresh_from_db()
        self.assertEqual(self.user.wallet, Decimal("10.00"))
        self.assertFalse(self.topup.status)
        self.assertEqual(models.MobileMoneyAlert.objects.get(transaction_id="70000000006").status, "Unclaimed")

    @override_settings(MOMO_CLAIM_WINDOW_HOURS=24)
    def test_claim_window(self):  # T14
        models.MobileMoneyAlert.objects.filter(pk=self.alert.pk).update(
            created_at=timezone.now() - timedelta(hours=25))
        self.claim("70000000001")
        self.alert.refresh_from_db(); self.user.refresh_from_db()
        self.assertEqual(self.alert.status, "Expired")
        self.assertEqual(self.user.wallet, Decimal("10.00"))

    def test_rate_limit_blocks_guessing(self):
        for i in range(8):
            self.claim(f"7000000010{i}")
        self.claim("70000000001")  # valid ID, but locked out
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet, Decimal("10.00"))
        self.assertEqual(models.MobileMoneyAlert.objects.get(pk=self.alert.pk).status, "Unclaimed")

    def test_login_required(self):
        self.client.logout()
        r = self.claim("70000000001")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(models.MobileMoneyAlert.objects.get(pk=self.alert.pk).status, "Unclaimed")

    def test_topup_info_redirects_to_claim(self):
        r = self.client.post(reverse("topup-info"), {"amount": "25", "method": "momo"})
        new = models.TopUpRequest.objects.exclude(pk=self.topup.pk).get()
        self.assertRedirects(r, reverse("momo_claim", args=[new.reference]), fetch_redirect_response=False)


class TopUpSwitchTests(TestCase):
    """The AdminInfo.topup_method switch decides where a top-up request goes."""

    def setUp(self):
        self.info = models.AdminInfo.objects.create(name="DANWEL", momo_number=244000000, phone_number=244000000,
                                                    payment_channel="MTN Mobile Money")
        self.user = models.CustomUser.objects.create_user(
            username="alice", password="pw-12345-long", email="a@example.com",
            first_name="a", last_name="x", status="User")
        self.client.force_login(self.user)

    def resolve(self, method, requested=None):
        self.info.topup_method = method
        return self.info.resolve_topup_method(requested)

    def test_resolve(self):
        self.assertEqual(self.resolve("manual", "momo"), "manual")
        self.assertEqual(self.resolve("manual", "paystack"), "manual")
        self.assertEqual(self.resolve("macrodroid", "paystack"), "momo")
        self.assertEqual(self.resolve("paystack", "momo"), "paystack")
        self.assertEqual(self.resolve("macrodroid_paystack", "paystack"), "paystack")
        self.assertEqual(self.resolve("macrodroid_paystack", "momo"), "momo")
        self.assertEqual(self.resolve("macrodroid_paystack", None), "momo")

    def post_topup(self, method, requested):
        self.info.topup_method = method
        self.info.save()
        return self.client.post(reverse("topup-info"), {"amount": "20", "method": requested})

    def test_manual_goes_to_old_page_even_if_momo_button_forged(self):
        r = self.post_topup("manual", "momo")
        ref = models.TopUpRequest.objects.get().reference
        self.assertRedirects(r, reverse("request_successful", args=[ref]), fetch_redirect_response=False)

    def test_macrodroid_goes_to_claim_page(self):
        r = self.post_topup("macrodroid", "paystack")
        ref = models.TopUpRequest.objects.get().reference
        self.assertRedirects(r, reverse("momo_claim", args=[ref]), fetch_redirect_response=False)

    def test_page_shows_buttons_for_switch(self):
        self.info.topup_method = "macrodroid_paystack"; self.info.save()
        r = self.client.get(reverse("topup-info"))
        self.assertContains(r, 'value="momo"'); self.assertContains(r, 'value="paystack"')
        self.info.topup_method = "manual"; self.info.save()
        r = self.client.get(reverse("topup-info"))
        self.assertNotContains(r, 'value="momo"'); self.assertNotContains(r, 'value="paystack"')


class MomoAdminTests(TestCase):  # T17, T18
    def test_admin_cannot_add_or_delete(self):
        admin_user = models.CustomUser.objects.create_superuser(
            username="root", password="pw-12345-long", email="root@example.com",
            first_name="r", last_name="r", status="User")
        alert = models.MobileMoneyAlert.objects.create(raw_sms_body="x", transaction_id="70000000001",
                                                       amount=Decimal("5"))
        self.client.force_login(admin_user)
        self.assertEqual(self.client.get("/admin/intel_app/mobilemoneyalert/add/").status_code, 403)
        self.assertEqual(self.client.get(f"/admin/intel_app/mobilemoneyalert/{alert.pk}/delete/").status_code, 403)
        self.assertEqual(self.client.get("/admin/intel_app/mobilemoneyalert/").status_code, 200)


class CleanupCommandTests(TestCase):  # T19
    def test_dry_run_and_delete(self):
        old = timezone.now() - timedelta(days=40)
        for i in range(5):
            models.MobileMoneyAlert.objects.create(raw_sms_body="junk", status="Ignored")
        models.MobileMoneyAlert.objects.create(raw_sms_body="x", transaction_id="1234567", amount=Decimal("5"),
                                               status="Claimed")
        models.MobileMoneyAlert.objects.create(raw_sms_body="x", transaction_id="1234568", amount=Decimal("5"))
        models.MobileMoneyAlert.objects.update(created_at=old)

        out = StringIO()
        call_command("cleanup_momo_alerts", "--dry-run", "--days", "30", stdout=out)
        self.assertIn("Would delete 5", out.getvalue())
        self.assertEqual(models.MobileMoneyAlert.objects.count(), 7)

        call_command("cleanup_momo_alerts", "--days", "30", stdout=StringIO())
        self.assertEqual(models.MobileMoneyAlert.objects.count(), 2)
        self.assertFalse(models.MobileMoneyAlert.objects.filter(status="Ignored").exists())
