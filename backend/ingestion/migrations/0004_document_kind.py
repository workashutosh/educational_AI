from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion", "0003_school_quotas_pending_onboard"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="kind",
            field=models.CharField(
                choices=[
                    ("notes", "Teaching notes"),
                    ("question_paper", "Previous year question paper"),
                ],
                db_index=True,
                default="notes",
                help_text="notes = teaching material; question_paper = past exam papers for mock tests.",
                max_length=32,
            ),
        ),
        migrations.AddIndex(
            model_name="document",
            index=models.Index(
                fields=["bucket", "kind", "status"],
                name="ingestion_d_bucket__kind_idx",
            ),
        ),
    ]
