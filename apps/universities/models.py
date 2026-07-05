from django.db import models

from apps.universities.formatting import format_direction_label


class MedicalUniversity(models.Model):
    class City(models.TextChoices):
        SPB = "spb", "Санкт-Петербург"
        MSK = "msk", "Москва"

    name = models.CharField("Название", max_length=255)
    city = models.CharField(
        "Город",
        max_length=8,
        choices=City.choices,
        blank=True,
    )
    api_config = models.JSONField("Конфиг API", default=dict, blank=True)
    is_active = models.BooleanField("Активен", default=True)
    honors_diploma_points = models.PositiveSmallIntegerField(
        "Баллы за аттестат с отличием", default=10
    )
    sync_interval_seconds = models.PositiveIntegerField(
        "Интервал синхронизации (сек)", default=3600
    )
    last_synced_at = models.DateTimeField("Последняя синхронизация", null=True, blank=True)
    sync_warning = models.TextField("Предупреждение синхронизации", blank=True)

    class Meta:
        verbose_name = "Медицинский университет"
        verbose_name_plural = "Медицинские университеты"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def has_api(self):
        return bool(self.api_config)


class StudyDirection(models.Model):
    university = models.ForeignKey(
        MedicalUniversity,
        on_delete=models.CASCADE,
        related_name="directions",
        verbose_name="Медицинский университет",
    )
    name = models.CharField("Название", max_length=255)
    filter_params = models.JSONField("Параметры фильтрации")
    min_fetch_score = models.PositiveSmallIntegerField(
        "Порог остановки пагинации", default=200
    )
    seats = models.PositiveSmallIntegerField(
        "Места", null=True, blank=True
    )

    class Meta:
        verbose_name = "Направление"
        verbose_name_plural = "Направления"
        ordering = ["university__name", "name"]

    def __str__(self):
        label = format_direction_label(self.name, self.seats)
        return f"{self.university.name} — {label}"
