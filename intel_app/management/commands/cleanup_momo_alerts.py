"""
Delete old Ignored / Expired MoMo alerts (junk SMS). Claimed rows are receipts and
Unclaimed rows may still be claimed, so neither is ever touched.

    python manage.py cleanup_momo_alerts --dry-run
    python manage.py cleanup_momo_alerts --days 30
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from intel_app.models import MobileMoneyAlert

logger = logging.getLogger(__name__)

PURGEABLE = [MobileMoneyAlert.STATUS_IGNORED, MobileMoneyAlert.STATUS_EXPIRED]


class Command(BaseCommand):
    help = "Deletes Ignored and Expired MoMo alerts older than N days. Never touches Claimed/Unclaimed."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without deleting.')
        parser.add_argument('--days', type=int, default=30, help='Retention window in days (default 30).')

    def handle(self, *args, **opts):
        days = opts['days']
        if days < 7:
            raise CommandError("--days must be at least 7 so recent junk SMS stay available for investigation.")

        cutoff = timezone.now() - timedelta(days=days)
        junk = MobileMoneyAlert.objects.filter(status__in=PURGEABLE, created_at__lt=cutoff)
        n = junk.count()
        if n == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to clean."))
            return

        if opts['dry_run']:
            self.stdout.write(self.style.SUCCESS(f"[DRY RUN] Would delete {n} alerts older than {days} days."))
            return

        deleted, _ = junk.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} old alerts."))
        logger.info("cleanup_momo_alerts deleted %s MoMo alerts older than %s days.", deleted, days)
