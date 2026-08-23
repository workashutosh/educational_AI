from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mock_tests", "0004_source_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="mocktest",
            name="reference_document_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
