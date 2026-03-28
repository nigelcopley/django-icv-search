"""Full reindex from Django models."""

from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from icv_search.models import SearchIndex
from icv_search.services.documents import reindex_all


class Command(BaseCommand):
    help = "Full reindex of a search index from Django model data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--index",
            type=str,
            required=True,
            help="Index name to reindex.",
        )
        parser.add_argument(
            "--model",
            type=str,
            required=True,
            help="Dotted path to model class (e.g. 'myapp.models.Product').",
        )
        parser.add_argument(
            "--tenant",
            type=str,
            default="",
            help="Tenant ID.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Documents per batch.",
        )

    def handle(self, *args, **options):
        try:
            index = SearchIndex.objects.get(
                name=options["index"],
                tenant_id=options["tenant"],
            )
        except SearchIndex.DoesNotExist as exc:
            raise CommandError(f"Index '{options['index']}' not found.") from exc

        try:
            model_class = import_string(options["model"])
        except ImportError as exc:
            raise CommandError(f"Cannot import model: {options['model']}") from exc

        total = reindex_all(index, model_class, batch_size=options["batch_size"])
        self.stdout.write(self.style.SUCCESS(f"Reindexed {total} documents in '{index.name}'."))
