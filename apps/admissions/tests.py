from django.test import SimpleTestCase, TestCase, override_settings
from unittest.mock import MagicMock, patch

from apps.admissions.clients.almazov_client import AlmazovClient
from apps.admissions.clients.almazov_html_parser import parse_seats, parse_table, rows_to_dicts
from apps.admissions.clients.base import RateLimitError
from apps.admissions.clients.gpmu_client import GPMUClient
from apps.admissions.clients.parsed import ParsedApplicantRow
from apps.admissions.clients.university_client import UniversityAPIClient
from apps.admissions.models import ApplicantProfile, SyncJob
from apps.admissions.services.position_service import PositionService
from apps.admissions.services.sync_service import should_skip_sync, sync_direction
from apps.universities.models import MedicalUniversity, StudyDirection
from apps.users.models import User
from django.utils import timezone
from datetime import timedelta


class ParsedApplicantRowTests(SimpleTestCase):
    def test_from_row_parses_valid_data(self):
        row = {
            "_position": 2,
            "_code": "1346542",
            "suniqcode": "1346542",
            "nsummark": "310",
            "npriority_ssp": "1",
            "sstatus_ssp": "Участвует в конкурсе",
        }
        parsed = ParsedApplicantRow.from_first_med_row(row)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.abiturient_id, "1346542")
        self.assertEqual(parsed.position, 2)
        self.assertEqual(parsed.nsummark, 310)
        self.assertEqual(parsed.npriority_ssp, 1)
        self.assertFalse(parsed.has_enrollment_consent)

    def test_from_first_med_parses_consent(self):
        row = {
            "_position": 1,
            "suniqcode": "1",
            "nsummark": "300",
            "npriority_ssp": "1",
            "sstatus_ssp": "Участвует",
            "ncons4enr": True,
        }
        parsed = ParsedApplicantRow.from_first_med_row(row)
        self.assertTrue(parsed.has_enrollment_consent)


class UniversityAPIClientTests(SimpleTestCase):
    def test_parse_retry_after_seconds(self):
        response = MagicMock()
        response.headers = {"Retry-After": "120"}
        self.assertEqual(UniversityAPIClient._parse_retry_after(response), 120)

    @patch("apps.admissions.clients.university_client.UniversityAPIClient._request_with_retry")
    def test_fetch_page_returns_rows(self, mock_request):
        mock_response = MagicMock()
        mock_response.json.return_value = {"rows": [{"suniqcode": "1", "nsummark": "300"}]}
        mock_request.return_value = mock_response

        client = UniversityAPIClient(
            {
                "base_url": "https://example.com",
                "list_endpoint": "/api/",
            }
        )
        client._csrf_token = "token"
        rows = client.fetch_page({}, offset=0)
        self.assertEqual(len(rows), 1)


class SyncServiceTests(TestCase):
    def setUp(self):
        self.university = MedicalUniversity.objects.create(
            name="Test MU",
            api_config={"base_url": "https://example.com", "list_endpoint": "/api/"},
            sync_interval_seconds=3600,
        )
        self.direction = StudyDirection.objects.create(
            university=self.university,
            name="Test Direction",
            filter_params={"sedprofile_name": "Test"},
        )

    def test_should_skip_sync_respects_interval(self):
        self.university.last_synced_at = timezone.now()
        self.university.save()
        self.assertTrue(should_skip_sync(self.university, force=False))
        self.assertFalse(should_skip_sync(self.university, force=True))

    @patch("apps.admissions.services.sync_service.get_university_client")
    def test_sync_direction_force_bypasses_interval(self, mock_get_client):
        self.university.last_synced_at = timezone.now()
        self.university.save()

        mock_client = mock_get_client.return_value
        mock_client.fetch_csrf_token.return_value = "csrf"
        mock_client.fetch_all_above_threshold.return_value = iter([])
        mock_client.last_seats = None

        result = sync_direction(self.direction.id, force=True, check_interval=False)
        self.assertEqual(result["status"], "success")

    @patch("apps.admissions.services.sync_service.get_university_client")
    def test_sync_direction_handles_429(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.fetch_csrf_token.side_effect = RateLimitError("limit", retry_after=60)
        mock_client.last_seats = None

        result = sync_direction(self.direction.id, force=True, check_interval=False)
        self.assertEqual(result["status"], "rate_limited")
        job = SyncJob.objects.get(direction=self.direction)
        self.assertEqual(job.status, SyncJob.Status.RATE_LIMITED)


class PositionServiceTests(TestCase):
    def setUp(self):
        self.university = MedicalUniversity.objects.create(
            name="Test MU",
            api_config={"base_url": "https://example.com"},
            honors_diploma_points=10,
        )
        self.direction = StudyDirection.objects.create(
            university=self.university,
            name="Pediatrics",
            filter_params={},
        )
        self.user = User.objects.create_user(
            abiturient_id="1000001",
            is_verified=True,
            ege_total_score=290,
            has_honors_diploma=True,
        )
        self.user.applied_universities.add(self.university)

        ApplicantProfile.objects.create(
            direction=self.direction,
            abiturient_id="1000001",
            position=5,
            sstatus_ssp="Участвует",
            nsummark=300,
            npriority_ssp=2,
        )
        ApplicantProfile.objects.create(
            direction=self.direction,
            abiturient_id="2000001",
            position=1,
            sstatus_ssp="Участвует",
            nsummark=310,
            npriority_ssp=1,
        )
        ApplicantProfile.objects.create(
            direction=self.direction,
            abiturient_id="2000002",
            position=2,
            sstatus_ssp="Участвует",
            nsummark=305,
            npriority_ssp=1,
        )
        ApplicantProfile.objects.create(
            direction=self.direction,
            abiturient_id="2000003",
            position=3,
            sstatus_ssp="Участвует",
            nsummark=280,
            npriority_ssp=2,
        )

    def test_current_position_from_profile(self):
        service = PositionService(self.user)
        positions = service.get_current_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].position, 5)
        self.assertFalse(positions[0].is_hypothetical)

    def test_forecast_among_other_priority_one(self):
        service = PositionService(self.user)
        forecast = service.get_forecast_positions()
        self.assertEqual(len(forecast), 1)
        # user score 300; other p1: 310, 305 -> position 3
        self.assertEqual(forecast[0].position, 3)
        self.assertFalse(forecast[0].is_hypothetical)

    def test_applied_without_profile_shows_estimate(self):
        user = User.objects.create_user(
            abiturient_id="9999999",
            is_verified=True,
            ege_total_score=290,
            has_honors_diploma=True,
        )
        user.applied_universities.add(self.university)

        service = PositionService(user)
        current = service.get_current_positions()[0]
        forecast = service.get_forecast_positions()[0]

        self.assertTrue(current.is_hypothetical)
        self.assertIn("9999999", current.sstatus_ssp)
        self.assertTrue(forecast.is_hypothetical)


    def test_profile_status_when_not_applied_but_in_list(self):
        user = User.objects.create_user(
            abiturient_id="2000001",
            is_verified=True,
            ege_total_score=250,
        )
        service = PositionService(user)
        current = service.get_current_positions()[0]
        self.assertTrue(current.is_hypothetical)
        self.assertEqual(current.sstatus_ssp, "Участвует")
        self.assertEqual(current.npriority_ssp, 1)


class GPMUClientTests(SimpleTestCase):
    def test_from_gpmu_row_parses_valid_data(self):
        row = {
            "Уникальный код": "1352247",
            "Сумма конкурсных баллов": "307",
            "Приоритет": "2",
            "Участвует в конкурсе": "✓",
            "Состояние договора": "✓",
        }
        parsed = ParsedApplicantRow.from_gpmu_row(row, position=5)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.abiturient_id, "1352247")
        self.assertEqual(parsed.position, 5)
        self.assertEqual(parsed.nsummark, 307)
        self.assertEqual(parsed.npriority_ssp, 2)
        self.assertEqual(parsed.sstatus_ssp, "Участвует в конкурсе")
        self.assertTrue(parsed.has_enrollment_consent)

    def test_from_gpmu_row_without_checkmarks(self):
        row = {
            "Уникальный код": "100",
            "Сумма конкурсных баллов": "250",
            "Приоритет": "3",
            "Участвует в конкурсе": "",
            "Состояние договора": "",
        }
        parsed = ParsedApplicantRow.from_gpmu_row(row, position=1)
        self.assertEqual(parsed.sstatus_ssp, "На рассмотрении")
        self.assertFalse(parsed.has_enrollment_consent)

    def test_threshold_skips_leading_zeros(self):
        self.assertFalse(GPMUClient._should_stop_at_score(0, 200))
        self.assertFalse(GPMUClient._should_stop_at_score(None, 200))
        self.assertFalse(GPMUClient._should_stop_at_score(250, 200))
        self.assertTrue(GPMUClient._should_stop_at_score(199, 200))

    @patch("apps.admissions.clients.gpmu_client.GPMUClient.fetch_group_page")
    def test_fetch_stops_after_threshold_not_on_zeros(self, mock_page):
        client = GPMUClient({"base_url": "https://spiski.gpmu.org", "page_size": 2})

        def fake_page(group_id, page=1, page_size=None):
            client.last_seats = 52
            if page == 1:
                return {
                    "rows": [
                        {"Уникальный код": "1", "Сумма конкурсных баллов": "0", "Приоритет": "1"},
                        {"Уникальный код": "2", "Сумма конкурсных баллов": "250", "Приоритет": "1"},
                    ],
                    "seats": {"total": 52},
                }
            return {
                "rows": [
                    {"Уникальный код": "3", "Сумма конкурсных баллов": "199", "Приоритет": "1"},
                ],
                "seats": {"total": 52},
            }

        mock_page.side_effect = fake_page
        rows = list(
            client.fetch_all_above_threshold({"group_id": "kg_4"}, min_score=200)
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Уникальный код"], "1")
        self.assertEqual(rows[1]["Уникальный код"], "2")
        self.assertEqual(client.last_seats, 52)


ALMAZOV_SAMPLE_HTML = """
<p class='number-places'>Всего мест: 162</p>
<table id='table-list'>
<tr class='original'><th>№</th><th>Уникальный код</th><th>Приоритет</th><th>БВИ </th>
<th>Сумма баллов</th><th>Сумма баллов по предметам</th><th>Биология</th><th>Химия</th>
<th>Русский язык</th><th>ВИ (Биология)</th><th>ВИ (Химия)</th><th>ВИ (Русский язык)</th>
<th>Сумма баллов за общие инд.дост.</th><th>Сумма баллов за инд.дост.</th>
<th>Сумма баллов за целевые инд.дост.</th><th>Текущий статус конкурса</th>
<th>Номер предложения</th><th>Состояние договора</th><th>Согласие на зачисление</th>
<th>Дата заявления</th></tr>
<tr class='copy'><td>1</td><td>1198285</td><td>1</td><td></td><td>304</td><td>294</td>
<td>100</td><td>100</td><td>94</td><td>ЕГЭ</td><td>ЕГЭ</td><td>ЕГЭ</td><td>10</td><td>10</td>
<td> 0</td><td>Участвует в конкурсе</td><td></td><td></td><td></td><td>30.06.2026</td></tr>
<td>3</td><td>1107909</td><td>1</td><td></td><td>303</td><td>293</td><td>96</td><td>100</td>
<td>97</td><td>ЕГЭ</td><td>ЕГЭ</td><td>ЕГЭ</td><td>10</td><td>10</td><td> 0</td>
<td>Участвует в конкурсе</td><td></td><td></td><td>✓</td><td>03.07.2026</td></tr>
<tr class='copy'><td>4</td><td>1183513</td><td>1</td><td></td><td>199</td><td>190</td>
<td>100</td><td>100</td><td>90</td><td>ЕГЭ</td><td>ЕГЭ</td><td>ЕГЭ</td><td>9</td><td>9</td>
<td> 0</td><td>На рассмотрении</td><td></td><td></td><td></td><td>01.07.2026</td></tr>
</table>
"""


class AlmazovClientTests(SimpleTestCase):
    def test_parse_seats(self):
        self.assertEqual(parse_seats(ALMAZOV_SAMPLE_HTML), 162)

    def test_parse_table_handles_broken_rows(self):
        headers, rows = parse_table(ALMAZOV_SAMPLE_HTML)
        self.assertEqual(headers[1], "Уникальный код")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][1], "1198285")
        self.assertEqual(rows[1][1], "1107909")

    def test_from_almazov_row_parses_valid_data(self):
        headers, rows = parse_table(ALMAZOV_SAMPLE_HTML)
        row = rows_to_dicts(headers, rows)[1]
        row["_position"] = 2
        parsed = ParsedApplicantRow.from_almazov_row(row, position=2)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.abiturient_id, "1107909")
        self.assertEqual(parsed.nsummark, 303)
        self.assertEqual(parsed.sstatus_ssp, "Участвует в конкурсе")
        self.assertTrue(parsed.has_enrollment_consent)

    @patch("apps.admissions.clients.almazov_client.AlmazovClient.fetch_list_html")
    def test_fetch_stops_at_threshold(self, mock_html):
        mock_html.return_value = ALMAZOV_SAMPLE_HTML
        client = AlmazovClient({"base_url": "https://abit.almazovcentre.ru"})
        rows = list(client.fetch_all_above_threshold({}, min_score=200))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Уникальный код"], "1198285")
        self.assertEqual(rows[1]["Уникальный код"], "1107909")
        self.assertEqual(client.last_seats, 162)


class AuthTests(TestCase):
    def test_unverified_user_cannot_login(self):
        User.objects.create_user(abiturient_id="999", is_verified=False)
        response = self.client.post("/login/", {"abiturient_id": "999"})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(response.status_code, 200)

    def test_verified_user_can_login(self):
        User.objects.create_user(abiturient_id="888", is_verified=True)
        response = self.client.post("/login/", {"abiturient_id": "888"})
        self.assertRedirects(response, "/")
        self.assertIn("_auth_user_id", self.client.session)

    def test_new_user_created_unverified(self):
        response = self.client.post("/login/", {"abiturient_id": "777"})
        self.assertTrue(User.objects.filter(abiturient_id="777", is_verified=False).exists())
        self.assertEqual(response.status_code, 200)
