"""Create a search index from the command line."""

from django.core.management.base import BaseCommand

from icv_search.services.indexing import create_index


class Command(BaseCommand):
    help = "Create a new search index."

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            type=str,
            required=True,
            help="Logical index name.",
        )
        parser.add_argument(
            "--primary-key",
            type=str,
            default="id",
            help="Primary key field (default: id).",
        )
        parser.add_argument(
            "--tenant",
            type=str,
            default="",
            help="Tenant ID.",
        )

    def handle(self, *args, **options):
        index = create_index(
            name=options["name"],
            tenant_id=options["tenant"],
            primary_key=options["primary_key"],
        )
        self.stdout.write(self.style.SUCCESS(f"Created index '{index.name}' (engine_uid: {index.engine_uid})."))
