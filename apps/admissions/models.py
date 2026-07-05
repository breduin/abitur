from django.db import models


class ApplicantProfile(models.Model):
    direction = models.ForeignKey(
        "universities.StudyDirection",
        on_delete=models.CASCADE,
        related_name="profiles",
        verbose_name="Направление",
    )
    abiturient_id = models.CharField("ID абитуриента", max_length=32, db_index=True)
    position = models.PositiveIntegerField("Позиция")
    sstatus_ssp = models.CharField("Статус заявления", max_length=255)
    nsummark = models.PositiveSmallIntegerField("Конкурсные баллы")
    npriority_ssp = models.PositiveSmallIntegerField("Приоритет")
    has_enrollment_consent = models.BooleanField(
        "Есть согласие на зачисление", default=False
    )
    raw_data = models.JSONField("Сырые данные", default=dict)
    fetched_at = models.DateTimeField("Дата получения", auto_now=True)

    class Meta:
        verbose_name = "Профиль абитуриента"
        verbose_name_plural = "Профили абитуриентов"
        constraints = [
            models.UniqueConstraint(
                fields=["direction", "abiturient_id"],
                name="unique_profile_per_direction",
            )
        ]
        ordering = ["direction", "position"]

    def __str__(self):
        return f"{self.abiturient_id} @ {self.direction} (#{self.position})"


class SyncJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидание"
        RUNNING = "running", "Выполняется"
        SUCCESS = "success", "Успех"
        ERROR = "error", "Ошибка"
        RATE_LIMITED = "rate_limited", "Rate limit"

    direction = models.OneToOneField(
        "universities.StudyDirection",
        on_delete=models.CASCADE,
        related_name="sync_job",
        verbose_name="Направление",
    )
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.PENDING
    )
    next_retry_at = models.DateTimeField("Повтор после", null=True, blank=True)
    last_error = models.TextField("Последняя ошибка", blank=True)
    records_fetched = models.PositiveIntegerField("Записей получено", default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Задача синхронизации"
        verbose_name_plural = "Задачи синхронизации"

    def __str__(self):
        return f"Sync {self.direction} [{self.status}]"


class AnalyticsSnapshot(models.Model):
    computed_at = models.DateTimeField("Рассчитано", auto_now_add=True)
    payload = models.JSONField("Данные")

    class Meta:
        verbose_name = "Снимок аналитики"
        verbose_name_plural = "Снимки аналитики"
        ordering = ["-computed_at"]

    def __str__(self):
        return f"Аналитика {self.computed_at:%d.%m.%Y %H:%M}"
