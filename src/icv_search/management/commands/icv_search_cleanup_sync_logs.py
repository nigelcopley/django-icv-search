"""Purge old IndexSyncLog entries."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Delete IndexSyncLog rows older than the given retention period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Delete logs older than this many days (default: ICV_SEARCH_SYNC_LOG_RETENTION_DAYS or 90).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report how many rows would be deleted without actually deleting.",
        )

    def handle(self, *args, **options):
        from datetime import timedelta

        from django.utils import timezone

        from icv_search.conf import ICV_SEARCH_SYNC_LOG_RETENTION_DAYS
        from icv_search.models import IndexSyncLog
        from icv_search.services.indexing import clear_sync_logs

        days = options["days"] if options["days"] is not None else ICV_SEARCH_SYNC_LOG_RETENTION_DAYS
        cutoff = timezone.now() - timedelta(days=days)
        count = IndexSyncLog.objects.filter(created_at__lt=cutoff).count()

        if options["dry_run"]:
            self.stdout.write(f"Would delete {count} sync log(s) older than {days} days.")
            return

        deleted = clear_sync_logs(days_older_than=days)
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} sync log(s) older than {days} days."))
