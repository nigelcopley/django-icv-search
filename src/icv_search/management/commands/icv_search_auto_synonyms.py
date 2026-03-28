"""Auto-create rewrite rules from synonym suggestions."""

import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create SearchRewrite rules from high-confidence synonym suggestions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--index",
            type=str,
            required=True,
            help="Index name.",
        )
        parser.add_argument(
            "--confidence",
            type=float,
            default=None,
            help="Minimum confidence to create a rewrite. Defaults to ICV_SEARCH_AUTO_SYNONYM_CONFIDENCE.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would be created without writing to the database.",
        )
        parser.add_argument(
            "--tenant-id",
            type=str,
            default="",
            help="Tenant scope.",
        )

    def handle(self, *args, **options):
        from django.core.exceptions import ImproperlyConfigured

        from icv_search.services.intelligence import auto_create_rewrites

        try:
            results = auto_create_rewrites(
                index_name=options["index"],
                confidence_threshold=options["confidence"],
                tenant_id=options["tenant_id"],
                dry_run=options["dry_run"],
            )
        except ImproperlyConfigured as exc:
            # pg_trgm not installed or merchandising not enabled
            self.stderr.write(self.style.ERROR(str(exc)))
            sys.exit(1)

        created = sum(1 for r in results if r["action"] == "created")
        skipped = sum(1 for r in results if r["action"] == "skipped")
        existing = sum(1 for r in results if r["action"] == "already_exists")

        for r in results:
            if r["action"] == "skipped":
                self.stdout.write(
                    f"Skipped (confidence {r['confidence']:.2f} < threshold): "
                    f'"{r["source_query"]}" -> "{r["suggested_synonym"]}"'
                )
            elif r["action"] == "already_exists":
                self.stdout.write(f'Already exists: "{r["source_query"]}" -> "{r["suggested_synonym"]}"')
            elif options["dry_run"]:
                self.stdout.write(
                    f'Would create: "{r["source_query"]}" -> "{r["suggested_synonym"]}" '
                    f"(confidence {r['confidence']:.2f})"
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Created: "{r["source_query"]}" -> "{r["suggested_synonym"]}" '
                        f"(confidence {r['confidence']:.2f})"
                    )
                )

        if options["dry_run"]:
            self.stdout.write(f"\nDry run - no records created. {created} would be created, {skipped} skipped.")
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\n{created} created, {existing} already existed, {skipped} skipped.")
            )
