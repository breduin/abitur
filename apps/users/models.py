from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, abiturient_id, **extra_fields):
        if not abiturient_id:
            raise ValueError("abiturient_id обязателен")
        user = self.model(abiturient_id=abiturient_id.strip(), **extra_fields)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, abiturient_id, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_verified", True)
        user = self.create_user(abiturient_id, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    abiturient_id = models.CharField("ID абитуриента", max_length=32, unique=True)
    is_verified = models.BooleanField("Верифицирован", default=False)
    ege_total_score = models.PositiveSmallIntegerField(
        "Суммарный балл ЕГЭ", null=True, blank=True
    )
    has_honors_diploma = models.BooleanField("Аттестат с отличием", default=False)
    applied_universities = models.ManyToManyField(
        "universities.MedicalUniversity",
        blank=True,
        related_name="applicants",
        verbose_name="Медицинский университет с поданными заявлениями",
    )
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "abiturient_id"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self):
        return self.abiturient_id
