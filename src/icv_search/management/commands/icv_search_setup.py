"""Set up search indexes: create missing SearchIndex records, sync settings, verify connectivity."""

from django.core.management.base import BaseCommand

from icv_search.backends import get_search_backend


class Command(BaseCommand):
    help = (
        "Create SearchIndex records for all models in ICV_SEARCH_AUTO_INDEX, "
        "sync settings to the engine, and verify connectivity."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without making changes.",
        )

    def handle(self, *args, **options):
        from django.apps import apps
        from django.conf import settings as django_settings

        from icv_search.models import SearchIndex
        from icv_search.services.indexing import _sync_index_to_engine, create_index

        dry_run = options["dry_run"]

        # 1. Check engine connectivity
        self.stdout.write("Checking search engine connectivity...")
        backend = get_search_backend()
        healthy = backend.health()

        if healthy:
            self.stdout.write(self.style.SUCCESS("  Engine is healthy."))
        else:
            self.stdout.write(self.style.ERROR("  Engine is unreachable. Check ICV_SEARCH_URL and ICV_SEARCH_API_KEY."))
            return

        # 2. Process ICV_SEARCH_AUTO_INDEX config
        auto_config = getattr(django_settings, "ICV_SEARCH_AUTO_INDEX", {})
        if not auto_config:
            self.stdout.write(
                self.style.WARNING(
                    "\nNo ICV_SEARCH_AUTO_INDEX configured. "
                    "Add index entries to settings to auto-create SearchIndex records."
                )
            )
            return

        self.stdout.write(f"\nFound {len(auto_config)} index(es) in ICV_SEARCH_AUTO_INDEX:")

        created_count = 0
        synced_count = 0
        error_count = 0

        for index_name, index_config in auto_config.items():
            model_path = index_config.get("model", "")
            self.stdout.write(f"\n  {index_name} ({model_path})")

            # Resolve model class
            model_class = None
            if model_path:
                try:
                    app_label, model_name = model_path.rsplit(".", 1)
                    model_class = apps.get_model(app_label, model_name)
                except (LookupError, ValueError):
                    self.stdout.write(self.style.WARNING(f"    Could not resolve model '{model_path}' — skipping."))
                    error_count += 1
                    continue

            # Check if SearchIndex already exists
            existing = SearchIndex.objects.filter(name=index_name).first()

            if existing:
                self.stdout.write(f"    SearchIndex record exists (engine_uid: {existing.engine_uid})")

                # Sync settings if not synced
                if not existing.is_synced:
                    if dry_run:
                        self.stdout.write("    Would sync settings to engine.")
                    else:
                        try:
                            _sync_index_to_engine(existing)
                            synced_count += 1
                            self.stdout.write(self.style.SUCCESS("    Synced settings to engine."))
                        except Exception as exc:
                            self.stdout.write(self.style.ERROR(f"    Failed to sync: {exc}"))
                            error_count += 1
                else:
                    self.stdout.write("    Settings already synced.")
                    synced_count += 1
            else:
                if dry_run:
                    self.stdout.write(self.style.WARNING(f"    Would create SearchIndex '{index_name}'"))
                else:
                    try:
                        index = create_index(name=index_name, model_class=model_class)
                        created_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(f"    Created SearchIndex (engine_uid: {index.engine_uid})")
                        )
                    except Exception as exc:
                        self.stdout.write(self.style.ERROR(f"    Failed to create: {exc}"))
                        error_count += 1

        # 3. Summary
        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes made."))
        else:
            parts = []
            if created_count:
                parts.append(f"{created_count} created")
            if synced_count:
                parts.append(f"{synced_count} synced")
            if error_count:
                parts.append(f"{error_count} errors")
            summary = ", ".join(parts) if parts else "nothing to do"
            self.stdout.write(self.style.SUCCESS(f"Setup complete: {summary}."))
