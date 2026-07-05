from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("universities", "0003_medicaluniversity_sync_warning"),
    ]

    operations = [
        migrations.AddField(
            model_name="medicaluniversity",
            name="city",
            field=models.CharField(
                blank=True,
                choices=[("spb", "Санкт-Петербург"), ("msk", "Москва")],
                max_length=8,
                verbose_name="Город",
            ),
        ),
    ]
