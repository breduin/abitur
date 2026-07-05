from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0002_applicantprofile_has_enrollment_consent"),
    ]

    operations = [
        migrations.CreateModel(
            name="AnalyticsSnapshot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("computed_at", models.DateTimeField(auto_now_add=True, verbose_name="Рассчитано")),
                ("payload", models.JSONField(verbose_name="Данные")),
            ],
            options={
                "verbose_name": "Снимок аналитики",
                "verbose_name_plural": "Снимки аналитики",
                "ordering": ["-computed_at"],
            },
        ),
    ]
