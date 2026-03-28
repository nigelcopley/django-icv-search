"""Sync index settings to the search engine."""

from django.core.management.base import BaseCommand

from icv_search.models import SearchIndex
from icv_search.services.indexing import _sync_index_to_engine


class Command(BaseCommand):
    help = "Sync search index settings to the engine."

    def add_arguments(self, parser):
        parser.add_argument(
            "--index",
            type=str,
            help="Sync a specific index by name.",
        )
        parser.add_argument(
            "--tenant",
            type=str,
            default="",
            help="Tenant ID filter.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-sync even if already marked as synced.",
        )

    def handle(self, *args, **options):
        qs = SearchIndex.objects.filter(is_active=True)

        if options["index"]:
            qs = qs.filter(name=options["index"])
        if options["tenant"]:
            qs = qs.filter(tenant_id=options["tenant"])
        if not options["force"]:
            qs = qs.filter(is_synced=False)

        if not qs.exists():
            self.stdout.write("No indexes to sync.")
            return

        total = qs.count()
        count = 0
        for index in qs:
            try:
                _sync_index_to_engine(index)
                self.stdout.write(self.style.SUCCESS(f"Synced: {index.name}"))
                count += 1
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"Failed: {index.name} — {exc}"))

        self.stdout.write(f"\nSynced {count}/{total} indexes.")
