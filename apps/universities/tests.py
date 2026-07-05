from django.test import TestCase

from apps.universities.models import MedicalUniversity, StudyDirection
from apps.universities.seed import (
    ALMAZOV_NAME,
    FIRST_MED_NAME,
    PEDIATRIC_NAME,
    MSU_NAME,
    PIROGOV_NAME,
    SECHENOV_NAME,
    SPBU_NAME,
    SZGMU_NAME,
    ensure_seed_data,
)


class SeedTests(TestCase):
    def test_ensure_seed_data_idempotent(self):
        ensure_seed_data()
        ensure_seed_data()

        self.assertEqual(MedicalUniversity.objects.filter(name=FIRST_MED_NAME).count(), 1)
        self.assertEqual(MedicalUniversity.objects.filter(name=PEDIATRIC_NAME).count(), 1)
        self.assertEqual(MedicalUniversity.objects.filter(name=ALMAZOV_NAME).count(), 1)
        self.assertEqual(MedicalUniversity.objects.filter(name=SZGMU_NAME).count(), 1)
        self.assertEqual(MedicalUniversity.objects.filter(name=SECHENOV_NAME).count(), 1)
        self.assertEqual(MedicalUniversity.objects.filter(name=PIROGOV_NAME).count(), 1)
        self.assertEqual(MedicalUniversity.objects.filter(name=MSU_NAME).count(), 1)
        self.assertEqual(MedicalUniversity.objects.filter(name=SPBU_NAME).count(), 1)
        self.assertEqual(StudyDirection.objects.count(), 13)

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

        szgmu = MedicalUniversity.objects.get(name=SZGMU_NAME)
        self.assertEqual(szgmu.api_config.get("provider"), "szgmu")
        lech = szgmu.directions.get(name="Лечебное дело")
        self.assertEqual(lech.seats, 97)
        self.assertEqual(
            lech.filter_params.get("list_path"),
            "/priem2026/spec/stage1/html/lech_budget.php",
        )

        sechenov = MedicalUniversity.objects.get(name=SECHENOV_NAME)
        self.assertEqual(sechenov.api_config.get("provider"), "sechenov")
        sechenov_groups = {
            d.filter_params.get("competitive_group_id") for d in sechenov.directions.all()
        }
        self.assertEqual(sechenov_groups, {"19488", "19486"})
        sechenov_seats = {d.name: d.seats for d in sechenov.directions.all()}
        self.assertEqual(sechenov_seats["Лечебное дело"], 495)
        self.assertEqual(sechenov_seats["Педиатрия"], 31)

        pirogov = MedicalUniversity.objects.get(name=PIROGOV_NAME)
        self.assertEqual(pirogov.api_config.get("provider"), "rsmu")
        pirogov_titles = {
            d.filter_params.get("program_title") for d in pirogov.directions.all()
        }
        self.assertIn("Лечебное дело (Лечебное дело) Общий конкурс 2026", pirogov_titles)
        self.assertIn("Педиатрия Общий конкурс 2026", pirogov_titles)
        pirogov_seats = {d.name: d.seats for d in pirogov.directions.all()}
        self.assertEqual(pirogov_seats["Лечебное дело"], 426)
        self.assertEqual(pirogov_seats["Педиатрия"], 283)

        msu = MedicalUniversity.objects.get(name=MSU_NAME)
        self.assertEqual(msu.api_config.get("provider"), "cpk_msu")
        self.assertEqual(msu.city, "msk")
        self.assertEqual(msu.honors_diploma_points, 0)
        lech = msu.directions.get(name="Лечебное дело")
        self.assertEqual(lech.seats, 46)
        self.assertEqual(lech.filter_params.get("list_path"), "/submitted/bachelor/dep_10")
        self.assertEqual(lech.filter_params.get("program_name"), "Лечебное дело")
        self.assertEqual(
            lech.filter_params.get("concourse_title"),
            "Основные места в рамках КЦП",
        )

        spbu = MedicalUniversity.objects.get(name=SPBU_NAME)
        self.assertEqual(spbu.api_config.get("provider"), "spbu")
        self.assertEqual(spbu.city, "spb")
        lech = spbu.directions.get(name="Лечебное дело")
        self.assertEqual(lech.seats, 21)
        self.assertEqual(
            lech.filter_params.get("report_priem_list_02_id"),
            "019f329a-c2d0-7107-8eea-e92731eaf3d1",
        )
        self.assertEqual(
            lech.filter_params.get("speciality_ids"),
            ["7dd29c4f-9a88-47e3-afa8-571940bf95fa"],
        )
