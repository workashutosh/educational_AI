from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mock_tests", "0003_results_release"),
    ]

    operations = [
        migrations.AddField(
            model_name="mocktest",
            name="source_mode",
            field=models.CharField(
                choices=[
                    ("notes", "Teaching notes"),
                    ("question_papers", "Previous year papers"),
                    ("both", "Notes + previous year papers"),
                ],
                default="notes",
                help_text="Which indexed bucket documents to use when generating questions.",
                max_length=32,
            ),
        ),
    ]
