from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("universities", "0002_studydirection_seats_alter_studydirection_university"),
    ]

    operations = [
        migrations.AddField(
            model_name="medicaluniversity",
            name="sync_warning",
            field=models.TextField(blank=True, verbose_name="Предупреждение синхронизации"),
        ),
    ]
