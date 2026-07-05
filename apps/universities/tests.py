from django.test import TestCase

from apps.universities.models import MedicalUniversity, StudyDirection
from apps.universities.seed import (
    ALMAZOV_NAME,
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
        self.assertEqual(MedicalUniversity.objects.filter(name=ALMAZOV_NAME).count(), 1)
        self.assertEqual(StudyDirection.objects.count(), 6)

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

        almazov = MedicalUniversity.objects.get(name=ALMAZOV_NAME)
        self.assertEqual(almazov.api_config.get("provider"), "almazov")
        almazov_seats = {d.name: d.seats for d in almazov.directions.all()}
        self.assertEqual(almazov_seats["Лечебное дело"], 162)
        self.assertEqual(almazov_seats["Педиатрия"], 16)
        almazov_files = {
            d.filter_params.get("file") for d in almazov.directions.all()
        }
        self.assertIn("000000060_31.05.01 Lechebnoe delo (Osnovnye mesta v ramkakh KTsP)_B.txt", almazov_files)
        self.assertIn("000000060_31.05.02 Pediatriya (Osnovnye mesta v ramkakh KTsP)_B.txt", almazov_files)
