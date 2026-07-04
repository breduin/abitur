from django.test import TestCase

from apps.universities.models import MedicalUniversity, StudyDirection
from apps.universities.seed import (
    FIRST_MED_NAME,
    PEDIATRIC_NAME,
    ensure_seed_data,
)


class SeedTests(TestCase):
    def test_ensure_seed_data_idempotent(self):
        ensure_seed_data()
        ensure_seed_data()

        self.assertEqual(MedicalUniversity.objects.filter(name=FIRST_MED_NAME).count(), 1)
        self.assertEqual(MedicalUniversity.objects.filter(name=PEDIATRIC_NAME).count(), 1)
        self.assertEqual(StudyDirection.objects.count(), 4)

        first_med = MedicalUniversity.objects.get(name=FIRST_MED_NAME)
        self.assertEqual(first_med.api_config.get("provider"), "1spbgmu")
        seats_by_name = {d.name: d.seats for d in first_med.directions.all()}
        self.assertEqual(seats_by_name["Лечебное дело"], 135)
        self.assertEqual(seats_by_name["Педиатрия"], 15)

        pediatric = MedicalUniversity.objects.get(name=PEDIATRIC_NAME)
        self.assertEqual(pediatric.api_config.get("provider"), "gpmu")
        group_ids = {
            d.filter_params.get("group_id")
            for d in pediatric.directions.all()
        }
        self.assertEqual(group_ids, {"kg_4", "kg_16"})
