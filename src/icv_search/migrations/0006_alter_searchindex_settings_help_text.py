"""Clarify SearchIndex.settings help text: engine settings use camelCase keys."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("icv_search", "0005_click_tracking"),
    ]

    operations = [
        migrations.AlterField(
            model_name="searchindex",
            name="settings",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Engine settings in the search engine's native camelCase form: "
                    "searchableAttributes, filterableAttributes, sortableAttributes, "
                    "synonyms, stopWords, rankingRules."
                ),
            ),
        ),
    ]
