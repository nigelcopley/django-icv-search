"""Roll up raw click events into daily aggregates."""

import datetime

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone


class Command(BaseCommand):
    help = "Aggregate SearchClick rows into SearchClickAggregate for a given date."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default="",
            help="Aggregate clicks for this date (ISO format YYYY-MM-DD). Defaults to yesterday.",
        )
        parser.add_argument(
            "--delete-raw",
            action="store_true",
            default=False,
            help="Delete raw SearchClick rows after aggregation.",
        )

    def handle(self, *args, **options):
        from icv_search.models.click_tracking import SearchClick, SearchClickAggregate

        if options["date"]:
            target_date = datetime.date.fromisoformat(options["date"])
        else:
            target_date = timezone.now().date() - datetime.timedelta(days=1)

        # Filter clicks for the target date
        clicks_qs = SearchClick.objects.filter(
            created_at__date=target_date,
        )

        # Group by (index_name, query, document_id, tenant_id) and count
        groups = clicks_qs.values("index_name", "query", "document_id", "tenant_id").annotate(click_count=Count("id"))

        created = 0
        updated = 0

        for group in groups:
            _, was_created = SearchClickAggregate.objects.update_or_create(
                index_name=group["index_name"],
                query=group["query"],
                document_id=group["document_id"],
                date=target_date,
                tenant_id=group["tenant_id"],
                defaults={"click_count": group["click_count"]},
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"Aggregated clicks for {target_date}: {created} created, {updated} updated.")
        )

        if options["delete_raw"]:
            deleted_count, _ = clicks_qs.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} raw SearchClick rows."))
