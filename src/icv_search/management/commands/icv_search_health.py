"""Check search engine connectivity."""

from django.core.management.base import BaseCommand

from icv_search.backends import get_search_backend
from icv_search.models import SearchIndex


class Command(BaseCommand):
    help = "Check search engine connectivity and report index stats."

    def add_arguments(self, parser):
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show per-index stats.",
        )

    def handle(self, *args, **options):
        backend = get_search_backend()
        healthy = backend.health()

        if healthy:
            self.stdout.write(self.style.SUCCESS("Search engine is healthy."))
        else:
            self.stdout.write(self.style.ERROR("Search engine is unreachable."))
            return

        if options["verbose"]:
            indexes = SearchIndex.objects.filter(is_active=True)
            self.stdout.write(f"\nActive indexes: {indexes.count()}")
            for index in indexes:
                try:
                    stats = backend.get_stats(uid=index.engine_uid)
                    docs = stats.get("numberOfDocuments", "?")
                    synced = "synced" if index.is_synced else "unsynced"
                    self.stdout.write(f"  {index.name} ({index.engine_uid}): {docs} docs, {synced}")
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f"  {index.name}: error — {exc}"))
