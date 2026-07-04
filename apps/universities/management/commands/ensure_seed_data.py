from django.core.management.base import BaseCommand

from apps.universities.seed import ensure_seed_data


class Command(BaseCommand):
    help = "Создаёт начальные данные медицинских университетов и направлений, если их нет"

    def handle(self, *args, **options):
        ensure_seed_data()
        self.stdout.write(self.style.SUCCESS("Seed data ensured."))
