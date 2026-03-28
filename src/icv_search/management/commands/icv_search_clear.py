"""Clear all documents from a search index."""

from django.core.management.base import BaseCommand, CommandError

from icv_search.backends import get_search_backend
from icv_search.models import SearchIndex


class Command(BaseCommand):
    help = "Remove all documents from a search index without deleting it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--index",
            type=str,
            required=True,
            help="Index name to clear.",
        )
        parser.add_argument(
            "--tenant",
            type=str,
            default="",
            help="Tenant ID.",
        )

    def handle(self, *args, **options):
        try:
            index = SearchIndex.objects.get(
                name=options["index"],
                tenant_id=options["tenant"],
            )
        except SearchIndex.DoesNotExist as exc:
            raise CommandError(f"Index '{options['index']}' not found.") from exc

        backend = get_search_backend()
        backend.clear_documents(uid=index.engine_uid)
        SearchIndex.objects.filter(pk=index.pk).update(document_count=0)

        self.stdout.write(self.style.SUCCESS(f"Cleared all documents from '{index.name}'."))
