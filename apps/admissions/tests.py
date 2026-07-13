from django.test import SimpleTestCase, TestCase, override_settings
from unittest.mock import MagicMock, patch

from apps.admissions.clients.almazov_client import AlmazovClient
from apps.admissions.clients.almazov_html_parser import parse_seats, parse_table, rows_to_dicts
from apps.admissions.clients.spbu_client import SPBUClient
from apps.admissions.clients.spbu_html_parser import parse_applicant_table
from apps.admissions.clients.spbu_html_parser import parse_seats as parse_spbu_seats
from apps.admissions.clients.cpk_msu_client import CPKMSUClient
from apps.admissions.clients.cpk_msu_html_parser import parse_concourse_section
from apps.admissions.clients.rsmu_client import RSMUClient
from apps.admissions.clients.rosunimed_client import RosunimedClient
from apps.admissions.clients.sechenov_client import SechenovClient
from apps.admissions.clients.sechenov_html_parser import parse_page_rows
from apps.admissions.clients.szgmu_client import SZGMUClient
from apps.admissions.clients.szgmu_html_parser import parse_budget_section
from apps.admissions.clients.szgmu_html_parser import rows_to_dicts as szgmu_rows_to_dicts
from apps.admissions.clients.base import RateLimitError, UniversityAPIError
from apps.admissions.clients.gpmu_client import (
    GPMUClient,
    GPMU_LECH_GROUP_NAME,
    GPMU_PED_GROUP_NAME,
)
from apps.admissions.clients.parsed import ParsedApplicantRow
from apps.admissions.clients.university_client import UniversityAPIClient
from apps.admissions.models import ApplicantProfile, SyncJob
from apps.admissions.services.applicant_overlap_service import (
    NOT_ENROLLED_LABEL,
    build_appearance_index,
    build_enrollment_labels_by_abiturient,
    get_applicant_overlap_rows,
    get_user_applied_directions,
)
from apps.admissions.services.analytics_service import (
    GROUP_MUSCOVITES,
    GROUP_PETERSBURGHERS,
    GROUP_VISITORS,
    save_analytics_snapshot,
)
from apps.admissions.services.consent_modeling_service import (
    compute_consent_model,
    get_user_consent_projection,
    get_user_hypothetical_consent_projection,
)
from apps.admissions.services.position_service import PositionService
from apps.admissions.services.sync_service import (
    mark_force_sync_started,
    should_skip_sync,
    sync_direction,
)
from apps.admissions.services.sync_status_service import get_sync_progress_context
from apps.universities.models import MedicalUniversity, StudyDirection
from apps.universities.seed import ALMAZOV_NAME, FIRST_MED_NAME, PEDIATRIC_NAME, SECHENOV_NAME, SZGMU_NAME
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

    @patch("apps.admissions.services.sync_service.get_university_client")
    def test_sync_direction_schedules_retry_on_transient_network_error(self, mock_get_client):
        mock_client = mock_get_client.return_value
        mock_client.fetch_csrf_token.side_effect = UniversityAPIError(
            "Сетевая ошибка: Failed to resolve 'spiski.gpmu.org'"
        )
        mock_client.last_seats = None

        result = sync_direction(self.direction.id, force=True, check_interval=False)
        self.assertEqual(result["status"], "network_retry")
        job = SyncJob.objects.get(direction=self.direction)
        self.assertEqual(job.status, SyncJob.Status.RATE_LIMITED)
        self.assertIsNotNone(job.next_retry_at)

    @patch("apps.admissions.services.sync_service.get_university_client")
    def test_sync_flushes_records_fetched_incrementally(self, mock_get_client):
        self.university.api_config = {
            "provider": "gpmu",
            "base_url": "https://example.com",
        }
        self.university.save(update_fields=["api_config"])

        mock_client = mock_get_client.return_value
        rows = [
            {
                "Уникальный код": str(index),
                "Сумма конкурсных баллов": "300",
                "Приоритет": "1",
                "Состояние договора": "",
            }
            for index in range(30)
        ]
        mock_client.fetch_all_above_threshold.return_value = iter(rows)
        mock_client.last_seats = 100

        result = sync_direction(self.direction.id, force=True, check_interval=False)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["records"], 30)

        job = SyncJob.objects.get(direction=self.direction)
        self.assertEqual(job.records_fetched, 30)

    def test_mark_force_sync_started_resets_jobs(self):
        job = SyncJob.objects.create(
            direction=self.direction,
            status=SyncJob.Status.SUCCESS,
            records_fetched=999,
        )
        updated = mark_force_sync_started()
        self.assertEqual(updated, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, SyncJob.Status.PENDING)
        self.assertEqual(job.records_fetched, 0)


class SyncStatusServiceTests(TestCase):
    def setUp(self):
        self.university = MedicalUniversity.objects.create(
            name="Test MU",
            api_config={"provider": "gpmu", "base_url": "https://example.com"},
        )
        self.direction = StudyDirection.objects.create(
            university=self.university,
            name="Лечебное дело",
            filter_params={},
            seats=100,
        )

    def test_get_sync_progress_context_running(self):
        SyncJob.objects.create(
            direction=self.direction,
            status=SyncJob.Status.RUNNING,
            records_fetched=50,
        )
        context = get_sync_progress_context()
        self.assertTrue(context["sync_is_active"])
        self.assertEqual(context["sync_running"], 1)
        row = context["sync_directions"][0]
        self.assertEqual(row.progress_percent, 50)
        self.assertFalse(row.is_indeterminate)

    def test_refresh_status_requires_login(self):
        response = self.client.get("/api/refresh/status/")
        self.assertEqual(response.status_code, 302)

    def test_sync_status_page_requires_login(self):
        response = self.client.get("/sync/")
        self.assertEqual(response.status_code, 302)

    def test_sync_status_page_for_verified_user(self):
        User.objects.create_user(abiturient_id="sync-user", is_verified=True)
        self.client.post("/login/", {"abiturient_id": "sync-user"})
        response = self.client.get("/sync/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Загрузка данных")
        self.assertContains(response, "Обновить данные сейчас")


class SourceUrlServiceTests(TestCase):
    def test_source_url_from_filter_params(self):
        university = MedicalUniversity.objects.create(
            name="Педиатрический (СПб)",
            api_config={"provider": "gpmu", "base_url": "https://spiski.gpmu.org"},
        )
        direction = StudyDirection.objects.create(
            university=university,
            name="Лечебное дело",
            filter_params={
                "group_id": "kg_4",
                "source_url": "https://spiski.gpmu.org/spisok-podavshikh",
            },
        )
        from apps.admissions.services.source_url_service import get_direction_source_url

        self.assertEqual(
            get_direction_source_url(direction),
            "https://spiski.gpmu.org/spisok-podavshikh",
        )


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

    def test_current_positions_include_source_url(self):
        self.direction.filter_params = {
            "source_url": "https://example.com/list",
        }
        self.direction.save(update_fields=["filter_params"])
        service = PositionService(self.user)
        positions = service.get_current_positions()
        self.assertEqual(positions[0].source_url, "https://example.com/list")

    def test_applied_without_profile_shows_not_found_when_list_loaded(self):
        user = User.objects.create_user(
            abiturient_id="9999999",
            is_verified=True,
            ege_total_score=290,
            has_honors_diploma=True,
        )
        user.applied_universities.add(self.university)

        service = PositionService(user)
        current = service.get_current_positions()[0]

        self.assertTrue(current.is_hypothetical)
        self.assertIn("9999999", current.sstatus_ssp)

    def test_applied_without_profile_shows_not_synced_when_list_empty(self):
        ApplicantProfile.objects.all().delete()
        user = User.objects.create_user(
            abiturient_id="1191858",
            is_verified=True,
            ege_total_score=290,
            has_honors_diploma=True,
        )
        user.applied_universities.add(self.university)

        service = PositionService(user)
        current = service.get_current_positions()[0]

        self.assertTrue(current.is_hypothetical)
        self.assertIn("ещё не загружены", current.sstatus_ssp)

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

    def test_fallback_ip_used_only_after_dns_error(self):
        client = GPMUClient(
            {
                "base_url": "https://spiski.gpmu.org",
                "fallback_ip": "89.169.170.237",
            }
        )
        self.assertEqual(client.base_url, "https://spiski.gpmu.org")

        with patch.object(client, "_fetch_group_page_once") as mock_once:
            mock_once.side_effect = [
                UniversityAPIError(
                    "Сетевая ошибка: Failed to resolve 'spiski.gpmu.org'"
                ),
                {"rows": [], "seats": {}},
            ]
            client.fetch_group_page("kg_4", page=1, page_size=1)
            self.assertEqual(mock_once.call_count, 2)
            self.assertFalse(mock_once.call_args_list[0].kwargs["use_fallback"])
            self.assertTrue(mock_once.call_args_list[1].kwargs["use_fallback"])

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

    def test_from_gpmu_row_treats_bvi_as_zero_score(self):
        row = {
            "Уникальный код": "1439926",
            "Сумма конкурсных баллов": "2",
            "Основание приема БВИ": "Диплом победителя олимпиады",
            "Приоритет": "1",
        }
        parsed = ParsedApplicantRow.from_gpmu_row(row, position=1)
        self.assertEqual(parsed.nsummark, 0)

    def test_fetch_skips_bvi_with_low_score_at_start(self):
        client = GPMUClient({"base_url": "https://spiski.gpmu.org", "page_size": 100})

        def fake_page(group_id, page=1, page_size=None):
            client.last_seats = 52
            return {
                "rows": [
                    {
                        "Уникальный код": "1439926",
                        "Сумма конкурсных баллов": "2",
                        "Основание приема БВИ": "Диплом победителя олимпиады",
                        "Приоритет": "1",
                    },
                    {
                        "Уникальный код": "1352247",
                        "Сумма конкурсных баллов": "307",
                        "Приоритет": "1",
                    },
                ],
                "seats": {"total": 52},
            }

        with patch.object(client, "fetch_group_page", side_effect=fake_page):
            rows = list(
                client.fetch_all_above_threshold({"group_id": "kg_4"}, min_score=200)
            )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Уникальный код"], "1439926")
        self.assertEqual(rows[1]["Уникальный код"], "1352247")

    @patch("apps.admissions.clients.gpmu_client.GPMUClient.fetch_group_page")
    def test_fetch_skips_olympiad_zeros_at_start(self, mock_page):
        client = GPMUClient({"base_url": "https://spiski.gpmu.org", "page_size": 100})

        def fake_page(group_id, page=1, page_size=None):
            client.last_seats = 201
            if page == 1:
                return {
                    "rows": [
                        {
                            "Уникальный код": "1300693",
                            "Сумма конкурсных баллов": "0",
                            "Основание приема БВИ": "Диплом победителя олимпиады",
                            "Приоритет": "1",
                        },
                        {
                            "Уникальный код": "1352247",
                            "Сумма конкурсных баллов": "307",
                            "Приоритет": "1",
                        },
                        {
                            "Уникальный код": "9999999",
                            "Сумма конкурсных баллов": "199",
                            "Приоритет": "1",
                        },
                    ],
                    "seats": {"total": 201},
                }
            return {"rows": [], "seats": {"total": 201}}

        mock_page.side_effect = fake_page
        rows = list(
            client.fetch_all_above_threshold({"group_id": "kg_18"}, min_score=200)
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Уникальный код"], "1300693")
        self.assertEqual(rows[1]["Уникальный код"], "1352247")
        self.assertEqual(client.last_seats, 201)

    def test_resolve_group_id_from_groups_api(self):
        import json
        from pathlib import Path

        sample = json.loads(
            Path(__file__).resolve().parents[2]
            .joinpath("dev/gpmu_groups.json")
            .read_text(encoding="utf-8")
        )
        client = GPMUClient({"base_url": "https://spiski.gpmu.org"})
        with patch.object(client, "fetch_groups", return_value=sample):
            self.assertEqual(
                client.resolve_group_id({"group_name": GPMU_LECH_GROUP_NAME}),
                "kg_4",
            )
            self.assertEqual(
                client.resolve_group_id({"group_name": GPMU_PED_GROUP_NAME}),
                "kg_18",
            )

    @patch("apps.admissions.clients.gpmu_client.GPMUClient.fetch_group_page")
    def test_fetch_resolves_group_name_before_request(self, mock_page):
        sample_groups = {
            "groups": [
                {"id": "kg_4", "name": GPMU_LECH_GROUP_NAME},
                {"id": "kg_18", "name": GPMU_PED_GROUP_NAME},
            ]
        }
        client = GPMUClient({"base_url": "https://spiski.gpmu.org", "page_size": 100})
        mock_page.return_value = {
            "rows": [
                {
                    "Уникальный код": "1352247",
                    "Сумма конкурсных баллов": "307",
                    "Приоритет": "1",
                },
            ],
            "seats": {"total": 201},
        }

        with patch.object(client, "fetch_groups", return_value=sample_groups):
            rows = list(
                client.fetch_all_above_threshold(
                    {"group_name": GPMU_PED_GROUP_NAME},
                    min_score=200,
                )
            )

        self.assertEqual(len(rows), 1)
        mock_page.assert_called()
        self.assertEqual(mock_page.call_args.args[0], "kg_18")


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

    @patch("apps.admissions.clients.almazov_client.AlmazovClient.fetch_list_html")
    def test_fetch_skips_bvi_at_start(self, mock_html):
        mock_html.return_value = """
        <p class='number-places'>Всего мест: 162</p>
        <table id='table-list'>
        <tr class='original'><th>№</th><th>Уникальный код</th><th>Приоритет</th><th>БВИ </th>
        <th>Сумма баллов</th><th>Текущий статус конкурса</th><th>Согласие на зачисление</th></tr>
        <td>1</td><td>1043997</td><td>1</td><td>✓</td><td>10</td><td>На рассмотрении</td><td></td></tr>
        <tr class='copy'><td>2</td><td>1508409</td><td>1</td><td></td><td>308</td>
        <td>Участвует в конкурсе</td><td></td></tr>
        <tr class='copy'><td>3</td><td>1183513</td><td>1</td><td></td><td>199</td>
        <td>На рассмотрении</td><td></td></tr>
        </table>
        """
        client = AlmazovClient({"base_url": "https://abit.almazovcentre.ru"})
        rows = list(client.fetch_all_above_threshold({}, min_score=200))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Уникальный код"], "1043997")
        self.assertEqual(rows[1]["Уникальный код"], "1508409")

    def test_from_almazov_row_treats_bvi_as_zero_score(self):
        row = {
            "Уникальный код": "1043997",
            "Сумма баллов": "10",
            "БВИ ": "✓",
            "Приоритет": "1",
            "Текущий статус конкурса": "На рассмотрении",
        }
        parsed = ParsedApplicantRow.from_almazov_row(row, position=1)
        self.assertEqual(parsed.nsummark, 0)


SZGMU_SAMPLE_HTML = """
<table>
<thead>
<tr>
<th></th><th>№ п/п</th><th>Уникальный<br>код<br>поступающего</th>
<th>Сумма<br>конкурсных<br>баллов</th><th>Сумма баллов<br>за вступит.<br>испытания</th>
<th>Балл<br>по химии<br>(физиологии чел.)</th><th>Балл<br>по биологии<br>(анатомии чел.)</th>
<th>Балл<br>по русскому<br>языку</th><th>Балл<br>за<br>инд. дост.</th>
<th>Балл<br>за целевые<br>инд. дост.</th><th>Преим.<br>право</th>
<th>Преим. право<br>в соотв. с п.70.1<br>Правил приема </th>
<th>Согласие<br>на<br>зачисление</th><th>Приоритет</th>
</tr>
</thead>
<tbody id='Бюджет'>
<tr>
<td class='bottom_line'><b>В рамках КЦП,<br>общий конкурс</b><br>(Количество мест - 97)</td>
<td>1</td><td>1214906</td><td>307</td><td>297</td><td>100</td><td>100</td><td>97</td>
<td>10</td><td>-</td><td>Нет</td><td>Нет</td><td>Нет</td><td>1</td>
</tr>
<td>2</td><td>1254508</td><td>307</td><td>297</td><td>97</td><td>100</td><td>100</td>
<td>10</td><td>-</td><td>Нет</td><td>Нет</td><td>Да</td><td>2</td>
</tr>
<td>3</td><td>1289187</td><td>199</td><td>189</td><td>100</td><td>98</td><td>97</td>
<td>10</td><td>-</td><td>Нет</td><td>Нет</td><td>Нет</td><td>1</td>
</tr>
</tbody>
</table>
"""


class SZGMUClientTests(SimpleTestCase):
    def test_parse_budget_section(self):
        seats, headers, rows = parse_budget_section(SZGMU_SAMPLE_HTML)
        self.assertEqual(seats, 97)
        self.assertEqual(headers[1], "Уникальный код поступающего")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][1], "1214906")

    def test_from_szgmu_row_parses_valid_data(self):
        _, headers, rows = parse_budget_section(SZGMU_SAMPLE_HTML)
        row = szgmu_rows_to_dicts(headers, rows)[1]
        parsed = ParsedApplicantRow.from_szgmu_row(row, position=2)
        self.assertEqual(parsed.abiturient_id, "1254508")
        self.assertEqual(parsed.nsummark, 307)
        self.assertEqual(parsed.npriority_ssp, 2)
        self.assertTrue(parsed.has_enrollment_consent)

    @patch("apps.admissions.clients.szgmu_client.SZGMUClient.fetch_list_html")
    def test_fetch_stops_at_threshold(self, mock_html):
        mock_html.return_value = SZGMU_SAMPLE_HTML
        client = SZGMUClient({"base_url": "https://szgmu.ru"})
        rows = list(
            client.fetch_all_above_threshold(
                {"list_path": "/priem2026/spec/stage1/html/lech_budget.php"},
                min_score=200,
            )
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Уникальный код поступающего"], "1214906")
        self.assertEqual(client.last_seats, 97)


class SechenovClientTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from pathlib import Path

        cls.sample_html = Path(__file__).resolve().parents[2].joinpath(
            "dev/sechenov_response.html"
        ).read_text(encoding="utf-8")

    def test_parse_page_rows(self):
        rows = parse_page_rows(self.sample_html)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["УИД"], "1106136")
        self.assertEqual(rows[0]["Сумма конкурсных баллов"], "310")
        self.assertEqual(rows[0]["Статус"], "Участвует в конкурсе")

    def test_from_sechenov_row_parses_valid_data(self):
        row = parse_page_rows(self.sample_html)[0]
        parsed = ParsedApplicantRow.from_sechenov_row(row, position=1)
        self.assertEqual(parsed.abiturient_id, "1106136")
        self.assertEqual(parsed.nsummark, 310)
        self.assertEqual(parsed.npriority_ssp, 1)
        self.assertTrue(parsed.has_enrollment_consent)

    def test_build_params_uses_page_prefix(self):
        client = SechenovClient({"base_url": "https://priem.sechenov.ru"})
        params = client._build_params("19488", page=3)
        self.assertEqual(params["appPage_19488"], "page-3")

    @patch("apps.admissions.clients.sechenov_client.SechenovClient.fetch_page_html")
    def test_fetch_paginates_until_threshold(self, mock_html):
        low_score_row = {
            "УИД": "9999999",
            "Сумма конкурсных баллов": "199",
            "Статус": "Участвует в конкурсе",
            "Приоритет зачисления": "1",
            "Подано согласие": "Нет",
        }

        def fake_page(filter_params, page):
            if page == 1:
                return self.sample_html
            if page == 2:
                return (
                    '<tr data-app="1"><td class="table-competition-lists__float">'
                    '<table class="table-competition-lists__inner-table"><tr>'
                    "<td>6</td><td>9999999</td></tr></table></td>"
                    "<td>—</td><td>199</td><td>189</td><td></td><td>10</td><td></td>"
                    "<td>Нет / Нет</td><td>Нет</td><td>1</td><td>Участвует в конкурсе</td></tr>"
                )
            return ""

        mock_html.side_effect = fake_page
        client = SechenovClient({"base_url": "https://priem.sechenov.ru"})
        rows = list(
            client.fetch_all_above_threshold(
                {"competitive_group_id": "19488", "seats": 495},
                min_score=200,
            )
        )
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-1]["УИД"], "1447524")
        self.assertEqual(client.last_seats, 495)

    @patch("apps.admissions.clients.sechenov_client.SechenovClient.fetch_page_html")
    def test_fetch_stops_on_duplicate_page(self, mock_html):
        def fake_page(filter_params, page):
            return self.sample_html

        mock_html.side_effect = fake_page
        client = SechenovClient({"base_url": "https://priem.sechenov.ru"})
        rows = list(
            client.fetch_all_above_threshold(
                {"competitive_group_id": "19488"},
                min_score=200,
            )
        )
        self.assertEqual(len(rows), 5)
        self.assertEqual(mock_html.call_count, 2)


RSMU_ROOT_JSON = [
    {
        "title": "Прием на обучение на специалитет - 2026",
        "file": "p1_spec.json",
        "showDiplomaAvg": False,
    },
]

RSMU_DATES_JSON = [
    {"title": "04.07.2026 19:00", "file": "p2_1154.json", "showDiplomaAvg": False},
]

RSMU_PROGRAMS_JSON = [
    {
        "title": "Лечебное дело (Лечебное дело) Общий конкурс 2026",
        "file": "p3_lech.json",
        "showDiplomaAvg": False,
    },
    {
        "title": "Педиатрия Общий конкурс 2026",
        "file": "p3_ped.json",
        "showDiplomaAvg": False,
    },
]

RSMU_APPLICANTS_JSON = {
    "program": "Лечебное дело (Лечебное дело) Общий конкурс 2026",
    "plan": 426,
    "count": 6,
    "applicants": [
        {
            "order": 1,
            "title": "1000000",
            "total": 10,
            "priority": 1,
            "state": "Подано",
            "approval": False,
            "noExam": True,
        },
        {
            "order": 99,
            "title": "1000001",
            "total": 0,
            "priority": 1,
            "state": "Подано",
            "approval": False,
        },
        {
            "order": 100,
            "title": "1000002",
            "total": 310,
            "priority": 1,
            "state": "Подано",
            "approval": True,
        },
        {
            "order": 101,
            "title": "1000003",
            "total": 200,
            "priority": 2,
            "state": "Подано",
            "approval": False,
        },
        {
            "order": 102,
            "title": "1000004",
            "total": 199,
            "priority": 1,
            "state": "Подано",
            "approval": False,
        },
    ],
}


class RSMUClientTests(SimpleTestCase):
    def setUp(self):
        from apps.admissions.clients import rsmu_client

        rsmu_client._NAV_CACHE.clear()

    def test_from_rsmu_row_parses_valid_data(self):
        row = RSMU_APPLICANTS_JSON["applicants"][2]
        parsed = ParsedApplicantRow.from_rsmu_row(row, position=3)
        self.assertEqual(parsed.abiturient_id, "1000002")
        self.assertEqual(parsed.position, 3)
        self.assertEqual(parsed.nsummark, 310)
        self.assertEqual(parsed.npriority_ssp, 1)
        self.assertTrue(parsed.has_enrollment_consent)

    @patch("apps.admissions.clients.rsmu_client.RSMUClient._fetch_json")
    def test_fetch_stops_at_threshold_skipping_zero_scores(self, mock_fetch):
        mock_fetch.side_effect = [
            RSMU_ROOT_JSON,
            RSMU_DATES_JSON,
            RSMU_PROGRAMS_JSON,
            RSMU_APPLICANTS_JSON,
        ]
        client = RSMUClient({"base_url": "https://submitted.rsmu.ru"})
        rows = list(
            client.fetch_all_above_threshold(
                {
                    "program_title": "Лечебное дело (Лечебное дело) Общий конкурс 2026",
                    "seats": 426,
                },
                min_score=200,
            )
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["title"], "1000000")
        self.assertEqual(rows[0]["_position"], 1)
        self.assertEqual(rows[-1]["title"], "1000003")
        self.assertEqual(client.last_seats, 426)
        self.assertEqual(client.sync_warning, "")

    @patch("apps.admissions.clients.rsmu_client.RSMUClient._fetch_json")
    def test_fetch_skips_noexam_with_low_scores(self, mock_fetch):
        mock_fetch.side_effect = [
            RSMU_ROOT_JSON,
            RSMU_DATES_JSON,
            RSMU_PROGRAMS_JSON,
            {
                "plan": 426,
                "applicants": [
                    {
                        "title": "1000000",
                        "total": 10,
                        "priority": 1,
                        "state": "Подано",
                        "noExam": True,
                    },
                    {
                        "title": "1000001",
                        "total": 250,
                        "priority": 1,
                        "state": "Подано",
                    },
                    {
                        "title": "1000002",
                        "total": 199,
                        "priority": 1,
                        "state": "Подано",
                    },
                ],
            },
        ]
        client = RSMUClient({"base_url": "https://submitted.rsmu.ru"})
        rows = list(
            client.fetch_all_above_threshold(
                {"program_title": "Лечебное дело (Лечебное дело) Общий конкурс 2026"},
                min_score=200,
            )
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "1000000")
        self.assertEqual(rows[1]["title"], "1000001")

    @patch("apps.admissions.clients.rsmu_client.RSMUClient._fetch_json")
    def test_multiple_dates_set_sync_warning(self, mock_fetch):
        mock_fetch.side_effect = [
            RSMU_ROOT_JSON,
            [
                {"title": "04.07.2026 19:00", "file": "p2_a.json"},
                {"title": "05.07.2026 12:00", "file": "p2_b.json"},
            ],
            RSMU_PROGRAMS_JSON,
            RSMU_APPLICANTS_JSON,
        ]
        client = RSMUClient({"base_url": "https://submitted.rsmu.ru"})
        list(
            client.fetch_all_above_threshold(
                {"program_title": "Педиатрия Общий конкурс 2026"},
                min_score=200,
            )
        )
        self.assertIn("несколько дат списков", client.sync_warning)
        self.assertIn("04.07.2026 19:00", client.sync_warning)


class CPKMSUClientTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from pathlib import Path

        cls.sample_html = Path(__file__).resolve().parents[2].joinpath(
            "dev/cpk_msu_dep_10.html"
        ).read_text(encoding="utf-8")

    def test_parse_concourse_section(self):
        seats, bvi_rows, main_rows = parse_concourse_section(
            self.sample_html,
            program_name="Лечебное дело",
            concourse_title="Основные места в рамках КЦП",
        )
        self.assertEqual(seats, 46)
        self.assertEqual(len(bvi_rows), 0)
        self.assertGreater(len(main_rows), 100)
        self.assertEqual(main_rows[0]["ID абитуриента"], "1187789")
        self.assertEqual(main_rows[0]["Сумма конкурсных баллов"], "298")

    def test_from_cpk_msu_row_parses_valid_data(self):
        _, _, main_rows = parse_concourse_section(
            self.sample_html,
            program_name="Лечебное дело",
            concourse_title="Основные места в рамках КЦП",
        )
        parsed = ParsedApplicantRow.from_cpk_msu_row(main_rows[0], position=1)
        self.assertEqual(parsed.abiturient_id, "1187789")
        self.assertEqual(parsed.nsummark, 298)
        self.assertEqual(parsed.npriority_ssp, 1)
        self.assertFalse(parsed.has_enrollment_consent)

    def test_from_cpk_msu_bvi_row_has_zero_score(self):
        row = {
            "ID абитуриента": "9999999",
            "Приоритет": "1",
            "Статус заявления": "На рассмотрении",
            "Наличие согласия на зачисление в МГУ": "Да",
            "_is_bvi": True,
        }
        parsed = ParsedApplicantRow.from_cpk_msu_row(row, position=1)
        self.assertEqual(parsed.nsummark, 0)
        self.assertTrue(parsed.has_enrollment_consent)

    @patch("apps.admissions.clients.cpk_msu_client.CPKMSUClient.fetch_list_html")
    def test_fetch_includes_bvi_before_main_and_stops_at_threshold(self, mock_html):
        bvi_table = """
        <h5>Лица, имеющие право на прием без вступительных испытаний</h5>
        <table class="submitted-table"><tbody>
        <tr><th>№</th><th>ID абитуриента</th><th>Приоритет</th><th>ИД</th>
        <th colspan="4">Баллы за вступительные испытания</th>
        <th>Согласие</th><th>Статус заявления</th></tr>
        <tr><th></th><th></th><th></th><th></th>
        <th>Химия</th><th>Биология</th><th>Русский</th><th>Доп</th>
        <th></th><th></th></tr>
        <tr><td>1</td><td>1000001</td><td>1</td><td>0</td>
        <td></td><td></td><td></td><td></td>
        <td>Да</td><td>На рассмотрении</td></tr>
        </tbody></table>
        """
        main_table = """
        <h5>Лица, не имеющие право на прием без вступительных испытаний</h5>
        <table class="submitted-table"><tbody>
        <tr><th>№</th><th>ID абитуриента</th><th>Приоритет</th>
        <th>Сумма конкурсных баллов</th><th>Сумма баллов за ВИ</th><th>ИД</th>
        <th colspan="4">Баллы за вступительные испытания</th>
        <th>Наличие согласия на зачисление в МГУ</th><th>Статус заявления</th></tr>
        <tr><th></th><th></th><th></th><th></th><th></th><th></th>
        <th>Химия</th><th>Биология</th><th>Русский</th><th>Доп</th>
        <th></th><th></th></tr>
        <tr><td>1</td><td>1000002</td><td>1</td><td>250</td><td>250</td><td>0</td>
        <td>100</td><td>100</td><td>50</td><td></td>
        <td>Нет</td><td>На рассмотрении</td></tr>
        <tr><td>2</td><td>1000003</td><td>1</td><td>199</td><td>199</td><td>0</td>
        <td>100</td><td>99</td><td>0</td><td></td>
        <td>Нет</td><td>На рассмотрении</td></tr>
        </tbody></table>
        """
        mock_html.return_value = f"""
        <h4 class="submitted-section-title">Образовательная программа: Лечебное дело</h4>
        <div class="submitted-concourse">
        <h4 class="submitted-concourse-title">Основные места в рамках КЦП</h4>
        <div>Всего мест: 46.</div>
        {bvi_table}
        <br>{main_table}
        </div>
        """
        client = CPKMSUClient({"base_url": "https://cpk.msu.ru"})
        rows = list(
            client.fetch_all_above_threshold(
                {
                    "list_path": "/submitted/bachelor/dep_10",
                    "program_name": "Лечебное дело",
                },
                min_score=200,
            )
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ID абитуриента"], "1000001")
        self.assertTrue(rows[0]["_is_bvi"])
        self.assertEqual(rows[1]["ID абитуриента"], "1000002")
        self.assertEqual(client.last_seats, 46)


class SPBUClientTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import json
        from pathlib import Path

        cls.sample_response = json.loads(
            Path(__file__).resolve().parents[2].joinpath("dev/spbu_api_response.json").read_text(
                encoding="utf-8"
            )
        )
        cls.sample_html = cls.sample_response["blocks"][0]["html"]

    def test_parse_seats_and_table(self):
        self.assertEqual(parse_spbu_seats(self.sample_html), 21)
        headers, rows = parse_applicant_table(self.sample_html)
        self.assertEqual(headers[1], "Уникальный код поступающего")
        self.assertGreater(len(rows), 100)
        self.assertEqual(rows[0][1], "1169071")
        self.assertEqual(rows[0][2], "БВИ (Победитель ОШ)")
        self.assertEqual(rows[2][2], "308")

    def test_from_spbu_row_parses_olympiad_and_regular(self):
        headers, rows = parse_applicant_table(self.sample_html)
        from apps.admissions.clients.spbu_html_parser import rows_to_dicts

        olympiad = rows_to_dicts(headers, rows)[0]
        regular = rows_to_dicts(headers, rows)[2]
        parsed_olympiad = ParsedApplicantRow.from_spbu_row(olympiad, position=1)
        parsed_regular = ParsedApplicantRow.from_spbu_row(regular, position=3)
        self.assertEqual(parsed_olympiad.abiturient_id, "1169071")
        self.assertEqual(parsed_olympiad.nsummark, 0)
        self.assertEqual(parsed_regular.abiturient_id, "1542510")
        self.assertEqual(parsed_regular.nsummark, 308)
        self.assertEqual(parsed_regular.npriority_ssp, 2)

    @patch("apps.admissions.clients.spbu_client.SPBUClient.fetch_report_meta")
    def test_build_request_body_uses_report_meta(self, mock_meta):
        mock_meta.return_value = {
            "id": "report-1",
            "report_upload_id": "upload-1",
            "sections": [
                {
                    "specialities": [
                        {
                            "id": "spec-1",
                            "code": "31.05.01",
                            "name": "Лечебное дело",
                        }
                    ]
                }
            ],
        }
        client = SPBUClient({"base_url": "https://enrollelists.spbu.ru"})
        body = client._build_request_body(
            {
                "filters": {
                    "program_name": "Лечебное дело",
                    "speciality": "31.05.01|Лечебное дело",
                }
            }
        )
        self.assertEqual(body["report_priem_list_02_id"], "report-1")
        self.assertEqual(body["speciality_ids"], ["spec-1"])
        self.assertEqual(body["filters"]["report_upload_id"], "upload-1")

    @patch("apps.admissions.clients.spbu_client.SPBUClient.fetch_list_html")
    def test_fetch_skips_olympiad_scores_at_threshold(self, mock_html):
        mock_html.return_value = """
        <div class="table-information"><table>
        <tr><th><div>Количество бюджетных мест:</div></th><td>21</td></tr>
        </table></div>
        <div class="table-data table-responsive mb-4">
        <table class="table table-bordered table-hover table-sm">
        <thead><tr>
        <th>№</th><th>Уникальный код поступающего</th><th>Сумма конкурсных баллов</th>
        <th>Сумма баллов за вступительные испытания</th><th>ВИ1</th><th>ВИ2</th><th>ВИ3</th>
        <th>ИД</th><th>П9</th><th>П10</th><th>Согласие на зачисление</th>
        <th>Приоритет зачисления, указанный поступающим по данной КГ</th><th>Статус</th>
        </tr></thead>
        <tbody>
        <tr><td>1</td><td>1000001</td><td>БВИ (Победитель ОШ)</td><td>0</td>
        <td></td><td></td><td></td><td>0</td><td>Нет</td><td>Нет</td><td>Нет</td><td>1</td><td>Участвует</td></tr>
        <tr><td>2</td><td>1000002</td><td>250</td><td>250</td>
        <td>100</td><td>100</td><td>50</td><td>0</td><td>Нет</td><td>Нет</td><td>Нет</td><td>1</td><td>Участвует</td></tr>
        <tr><td>3</td><td>1000003</td><td>199</td><td>199</td>
        <td>100</td><td>99</td><td>0</td><td>0</td><td>Нет</td><td>Нет</td><td>Нет</td><td>1</td><td>Участвует</td></tr>
        </tbody></table></div>
        """
        client = SPBUClient({"base_url": "https://enrollelists.spbu.ru"})
        rows = list(
            client.fetch_all_above_threshold(
                {
                    "report_priem_list_02_id": "test",
                    "speciality_ids": ["7dd29c4f-9a88-47e3-afa8-571940bf95fa"],
                    "filters": {},
                },
                min_score=200,
            )
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Уникальный код поступающего"], "1000001")
        self.assertEqual(rows[1]["Уникальный код поступающего"], "1000002")
        self.assertEqual(client.last_seats, 21)


class RosunimedClientTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import json
        from pathlib import Path

        cls.sample_response = json.loads(
            Path(__file__).resolve().parents[2]
            .joinpath("dev/rosunimed_group_000002336.json")
            .read_text(encoding="utf-8")
        )

    def test_from_rosunimed_row_parses_olympiad_and_regular(self):
        olympiad = self.sample_response["incoming"][0]
        regular = self.sample_response["incoming"][6]
        parsed_olympiad = ParsedApplicantRow.from_rosunimed_row(olympiad, position=1)
        parsed_regular = ParsedApplicantRow.from_rosunimed_row(regular, position=7)
        self.assertEqual(parsed_olympiad.abiturient_id, "1393536")
        self.assertEqual(parsed_olympiad.nsummark, 0)
        self.assertTrue(parsed_olympiad.has_enrollment_consent)
        self.assertEqual(parsed_olympiad.sstatus_ssp, "На рассмотрении")
        self.assertEqual(parsed_regular.abiturient_id, "1437739")
        self.assertEqual(parsed_regular.nsummark, 310)
        self.assertEqual(parsed_regular.npriority_ssp, 1)

    def test_parse_competition_score_handles_bvi_and_empty(self):
        olympiad = self.sample_response["incoming"][1]
        regular = self.sample_response["incoming"][6]
        empty = self.sample_response["incoming"][3172]
        self.assertEqual(RosunimedClient._parse_competition_score(olympiad), 0)
        self.assertEqual(RosunimedClient._parse_competition_score(regular), 310)
        self.assertIsNone(RosunimedClient._parse_competition_score(empty))

    @patch("apps.admissions.clients.rosunimed_client.RosunimedClient.fetch_group")
    def test_fetch_skips_bvi_at_threshold_and_stops_on_low_score(self, mock_group):
        incoming = [
            {
                "uniqueId": "1",
                "ratingTotal": "10",
                "priority": "1",
                "reasonWithoutAdmission": "Диплом победителя олимпиады",
                "consent": True,
                "status": "На рассмотрении",
            },
            {
                "uniqueId": "2",
                "ratingTotal": "250",
                "priority": "1",
                "consent": False,
                "status": "На рассмотрении",
            },
            {
                "uniqueId": "3",
                "ratingTotal": "199",
                "priority": "1",
                "consent": False,
                "status": "На рассмотрении",
            },
            {
                "uniqueId": "4",
                "ratingTotal": "",
                "priority": "1",
                "consent": False,
                "status": "На рассмотрении",
            },
        ]
        mock_group.return_value = {"count": 98, "incoming": incoming}
        client = RosunimedClient({"base_url": "https://contest.rosunimed.ru"})

        def fetch_group_side_effect(group_id):
            client.last_seats = 98
            return mock_group.return_value

        mock_group.side_effect = fetch_group_side_effect
        rows = list(
            client.fetch_all_above_threshold({"group_id": "000002336"}, min_score=200)
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["uniqueId"], "1")
        self.assertEqual(rows[1]["uniqueId"], "2")
        self.assertEqual(client.last_seats, 98)


class ApplicantOverlapServiceTests(TestCase):
    def setUp(self):
        self.spb_uni = MedicalUniversity.objects.create(
            name="SPB Overlap",
            city=MedicalUniversity.City.SPB,
        )
        self.msk_uni = MedicalUniversity.objects.create(
            name="MSK Overlap",
            city=MedicalUniversity.City.MSK,
        )
        self.spb_direction = StudyDirection.objects.create(
            university=self.spb_uni,
            name="Лечебное дело",
            filter_params={},
            seats=10,
        )
        self.msk_direction = StudyDirection.objects.create(
            university=self.msk_uni,
            name="Лечебное дело",
            filter_params={},
            seats=10,
        )
        self.user = User.objects.create_user(abiturient_id="9001", is_verified=True)
        self.user.applied_universities.add(self.spb_uni, self.msk_uni)

        ApplicantProfile.objects.create(
            direction=self.spb_direction,
            abiturient_id="A100",
            position=1,
            sstatus_ssp="Участвует",
            nsummark=300,
            npriority_ssp=1,
        )
        ApplicantProfile.objects.create(
            direction=self.msk_direction,
            abiturient_id="A100",
            position=5,
            sstatus_ssp="Участвует",
            nsummark=295,
            npriority_ssp=2,
        )
        ApplicantProfile.objects.create(
            direction=self.spb_direction,
            abiturient_id="A200",
            position=2,
            sstatus_ssp="Участвует",
            nsummark=290,
            npriority_ssp=1,
        )

    def test_get_user_applied_directions(self):
        directions = get_user_applied_directions(self.user)
        self.assertEqual(len(directions), 2)
        self.assertEqual({direction.id for direction in directions}, {
            self.spb_direction.id,
            self.msk_direction.id,
        })

    def test_overlap_rows_show_other_lists(self):
        index = build_appearance_index()
        rows = get_applicant_overlap_rows(
            self.spb_direction.id,
            limit=10,
            appearance_index=index,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].abiturient_id, "A100")
        self.assertEqual(rows[0].position, 1)
        self.assertEqual(rows[0].nsummark, 300)
        self.assertIn("MSK Overlap", rows[0].other_applications)
        self.assertEqual(rows[1].abiturient_id, "A200")
        self.assertEqual(rows[1].position, 2)
        self.assertEqual(rows[1].nsummark, 290)
        self.assertEqual(rows[1].other_applications, "Только в выбранном списке")

    def test_overlap_rows_include_modeling_result(self):
        index = build_appearance_index()
        enrollment_labels = {"A100": "MSK Overlap — Лечебное дело"}
        rows = get_applicant_overlap_rows(
            self.spb_direction.id,
            limit=10,
            appearance_index=index,
            enrollment_labels=enrollment_labels,
        )
        self.assertEqual(rows[0].modeling_result, "MSK Overlap — Лечебное дело")
        self.assertEqual(rows[1].modeling_result, NOT_ENROLLED_LABEL)

    def test_overlap_rows_enrolled_only_filter(self):
        index = build_appearance_index()
        consent_modeling = {
            "enrollment_by_direction": {
                str(self.spb_direction.id): ["A200"],
            }
        }
        rows = get_applicant_overlap_rows(
            self.spb_direction.id,
            limit=10,
            appearance_index=index,
            consent_modeling=consent_modeling,
            enrolled_only=True,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].abiturient_id, "A200")

    def test_build_enrollment_labels_from_consent_modeling(self):
        consent_modeling = {
            "enrollment_by_direction": {
                str(self.msk_direction.id): ["A100"],
            }
        }
        labels = build_enrollment_labels_by_abiturient(consent_modeling)
        self.assertEqual(labels["A100"], "MSK Overlap — Лечебное дело")


class AnalyticsServiceTests(TestCase):
    def setUp(self):
        self.spb_uni = MedicalUniversity.objects.create(
            name="SPB Test",
            city=MedicalUniversity.City.SPB,
        )
        self.msk_uni = MedicalUniversity.objects.create(
            name="MSK Test",
            city=MedicalUniversity.City.MSK,
        )
        self.spb_direction = StudyDirection.objects.create(
            university=self.spb_uni,
            name="Лечебное дело",
            filter_params={},
            seats=10,
        )
        self.msk_direction = StudyDirection.objects.create(
            university=self.msk_uni,
            name="Лечебное дело",
            filter_params={},
            seats=20,
        )
        SyncJob.objects.create(direction=self.spb_direction, records_fetched=100)
        SyncJob.objects.create(direction=self.msk_direction, records_fetched=200)

    def test_compute_groups(self):
        ApplicantProfile.objects.create(
            direction=self.spb_direction,
            abiturient_id="1001",
            position=1,
            sstatus_ssp="Участвует",
            nsummark=300,
            npriority_ssp=1,
        )
        ApplicantProfile.objects.create(
            direction=self.msk_direction,
            abiturient_id="1002",
            position=1,
            sstatus_ssp="Участвует",
            nsummark=290,
            npriority_ssp=1,
        )
        ApplicantProfile.objects.create(
            direction=self.spb_direction,
            abiturient_id="1003",
            position=2,
            sstatus_ssp="Участвует",
            nsummark=280,
            npriority_ssp=1,
        )
        ApplicantProfile.objects.create(
            direction=self.msk_direction,
            abiturient_id="1003",
            position=2,
            sstatus_ssp="Участвует",
            nsummark=280,
            npriority_ssp=1,
        )

        payload = save_analytics_snapshot()
        overall = payload["overall"]
        self.assertEqual(overall["total"], 3)
        self.assertEqual(overall[GROUP_PETERSBURGHERS]["count"], 1)
        self.assertEqual(overall[GROUP_MUSCOVITES]["count"], 1)
        self.assertEqual(overall[GROUP_VISITORS]["count"], 1)

        spb_row = next(row for row in payload["directions"] if row["city"] == "spb")
        msk_row = next(row for row in payload["directions"] if row["city"] == "msk")
        self.assertEqual(spb_row["applications_count"], 100)
        self.assertEqual(msk_row["applications_count"], 200)

        spb_groups = {item["key"]: item for item in spb_row["groups"]}
        self.assertIn(GROUP_PETERSBURGHERS, spb_groups)
        self.assertIn(GROUP_VISITORS, spb_groups)
        self.assertNotIn(GROUP_MUSCOVITES, spb_groups)
        self.assertEqual(spb_groups[GROUP_PETERSBURGHERS]["count"], 1)
        self.assertEqual(spb_groups[GROUP_VISITORS]["count"], 1)

        msk_groups = {item["key"]: item for item in msk_row["groups"]}
        self.assertIn(GROUP_MUSCOVITES, msk_groups)
        self.assertIn(GROUP_VISITORS, msk_groups)
        self.assertNotIn(GROUP_PETERSBURGHERS, msk_groups)

    def test_full_spb_coverage(self):
        spb_uni_2 = MedicalUniversity.objects.create(
            name="SPB Test 2",
            city=MedicalUniversity.City.SPB,
        )
        spb_direction_2 = StudyDirection.objects.create(
            university=spb_uni_2,
            name="Педиатрия",
            filter_params={},
            seats=5,
        )

        for direction, abiturient_id, position in [
            (self.spb_direction, "2001", 1),
            (spb_direction_2, "2001", 1),
            (self.spb_direction, "2002", 2),
            (self.msk_direction, "2001", 1),
        ]:
            ApplicantProfile.objects.create(
                direction=direction,
                abiturient_id=abiturient_id,
                position=position,
                sstatus_ssp="Участвует",
                nsummark=300,
                npriority_ssp=1,
            )

        payload = save_analytics_snapshot()
        coverage = payload["full_spb_coverage"]
        self.assertEqual(coverage["directions_count"], 2)
        self.assertEqual(coverage["total"], 1)

        by_key = {
            (row["university_name"], row["direction_name"]): row
            for row in coverage["directions"]
        }
        self.assertEqual(len(coverage["directions"]), 2)
        spb_row = by_key[(self.spb_uni.name, "Лечебное дело")]
        spb_row_2 = by_key[(spb_uni_2.name, "Педиатрия")]

        self.assertEqual(spb_row["count"], 1)
        self.assertEqual(spb_row["percent"], 50.0)
        self.assertEqual(spb_row_2["count"], 1)
        self.assertEqual(spb_row_2["percent"], 100.0)

    def test_spb_lech_coverage(self):
        spb_uni_2 = MedicalUniversity.objects.create(
            name="SPB Test 2",
            city=MedicalUniversity.City.SPB,
        )
        spb_lech_2 = StudyDirection.objects.create(
            university=spb_uni_2,
            name="Лечебное дело",
            filter_params={},
            seats=5,
        )
        spb_ped = StudyDirection.objects.create(
            university=spb_uni_2,
            name="Педиатрия",
            filter_params={},
            seats=5,
        )

        for direction, abiturient_id, position in [
            (self.spb_direction, "3001", 1),
            (spb_lech_2, "3001", 1),
            (self.spb_direction, "3002", 2),
            (spb_ped, "3001", 1),
        ]:
            ApplicantProfile.objects.create(
                direction=direction,
                abiturient_id=abiturient_id,
                position=position,
                sstatus_ssp="Участвует",
                nsummark=300,
                npriority_ssp=1,
            )

        payload = save_analytics_snapshot()
        coverage = payload["spb_lech_coverage"]
        self.assertEqual(coverage["directions_count"], 2)
        self.assertEqual(coverage["total"], 1)

        by_uni = {row["university_name"]: row for row in coverage["directions"]}
        self.assertEqual(len(coverage["directions"]), 2)
        self.assertEqual(by_uni[self.spb_uni.name]["count"], 1)
        self.assertEqual(by_uni[self.spb_uni.name]["percent"], 50.0)
        self.assertEqual(by_uni[spb_uni_2.name]["count"], 1)
        self.assertEqual(by_uni[spb_uni_2.name]["percent"], 100.0)

    def test_analytics_page_requires_login(self):
        response = self.client.get("/analytics/")
        self.assertEqual(response.status_code, 302)

    def test_analytics_page_for_verified_user(self):
        User.objects.create_user(abiturient_id="777", is_verified=True)
        self.client.post("/login/", {"abiturient_id": "777"})
        response = self.client.get("/analytics/")
        self.assertEqual(response.status_code, 200)


class ConsentModelingServiceTests(TestCase):
    def _create_profile(self, direction, abiturient_id, *, position, npriority, nsummark, raw_data=None):
        return ApplicantProfile.objects.create(
            direction=direction,
            abiturient_id=abiturient_id,
            position=position,
            sstatus_ssp="Участвует",
            nsummark=nsummark,
            npriority_ssp=npriority,
            raw_data=raw_data or {},
        )

    def test_consent_prefers_higher_ranked_passing_university(self):
        sechenov = MedicalUniversity.objects.create(
            name=SECHENOV_NAME,
            city=MedicalUniversity.City.MSK,
        )
        first_med = MedicalUniversity.objects.create(
            name=FIRST_MED_NAME,
            city=MedicalUniversity.City.SPB,
        )
        sechenov_lech = StudyDirection.objects.create(
            university=sechenov,
            name="Лечебное дело",
            filter_params={},
            seats=10,
        )
        first_med_lech = StudyDirection.objects.create(
            university=first_med,
            name="Лечебное дело",
            filter_params={},
            seats=10,
        )

        self._create_profile(sechenov_lech, "A1", position=1, npriority=1, nsummark=300)
        self._create_profile(first_med_lech, "A1", position=1, npriority=1, nsummark=300)

        model = compute_consent_model()
        self.assertEqual(model["consent_by_abiturient"]["A1"], sechenov.id)

    def test_consent_prefers_first_med_over_pediatric_when_passing(self):
        first_med = MedicalUniversity.objects.create(
            name=FIRST_MED_NAME,
            city=MedicalUniversity.City.SPB,
        )
        pediatric = MedicalUniversity.objects.create(
            name=PEDIATRIC_NAME,
            city=MedicalUniversity.City.SPB,
        )
        first_med_ped = StudyDirection.objects.create(
            university=first_med,
            name="Педиатрия",
            filter_params={},
            seats=10,
        )
        pediatric_ped = StudyDirection.objects.create(
            university=pediatric,
            name="Педиатрия",
            filter_params={},
            seats=10,
        )

        self._create_profile(pediatric_ped, "A2", position=1, npriority=2, nsummark=290)
        self._create_profile(first_med_ped, "A2", position=5, npriority=1, nsummark=290)

        model = compute_consent_model()
        self.assertEqual(model["consent_by_abiturient"]["A2"], first_med.id)
        competitive_first_med = model["competitive_by_direction"][str(first_med_ped.id)]
        self.assertIn("A2", competitive_first_med)

    def test_enrolls_at_lower_ranked_university_when_not_admitted_higher(self):
        first_med = MedicalUniversity.objects.create(name=FIRST_MED_NAME, city=MedicalUniversity.City.SPB)
        pediatric = MedicalUniversity.objects.create(name=PEDIATRIC_NAME, city=MedicalUniversity.City.SPB)
        first_med_lech = StudyDirection.objects.create(
            university=first_med,
            name="Лечебное дело",
            filter_params={},
            seats=1,
        )
        pediatric_lech = StudyDirection.objects.create(
            university=pediatric,
            name="Лечебное дело",
            filter_params={},
            seats=5,
        )

        self._create_profile(first_med_lech, "BLOCK1", position=1, npriority=1, nsummark=300)
        self._create_profile(first_med_lech, "A3", position=7, npriority=1, nsummark=280)
        self._create_profile(pediatric_lech, "A3", position=2, npriority=1, nsummark=280)

        model = compute_consent_model()
        self.assertNotIn("A3", model["enrollment_by_direction"].get(str(first_med_lech.id), []))
        self.assertIn("A3", model["enrollment_by_direction"][str(pediatric_lech.id)])
        self.assertEqual(model["consent_by_abiturient"]["A3"], pediatric.id)

    def test_pediatric_enrollment_over_almazov_with_updated_rank(self):
        almazov = MedicalUniversity.objects.create(name=ALMAZOV_NAME, city=MedicalUniversity.City.SPB)
        pediatric = MedicalUniversity.objects.create(name=PEDIATRIC_NAME, city=MedicalUniversity.City.SPB)
        almazov_ped = StudyDirection.objects.create(
            university=almazov,
            name="Педиатрия",
            filter_params={},
            seats=16,
        )
        pediatric_ped = StudyDirection.objects.create(
            university=pediatric,
            name="Педиатрия",
            filter_params={},
            seats=201,
        )

        for index in range(1, 16):
            self._create_profile(
                almazov_ped,
                f"LOW{index}",
                position=index,
                npriority=1,
                nsummark=250,
            )
        self._create_profile(almazov_ped, "USERZ", position=35, npriority=1, nsummark=287)
        self._create_profile(pediatric_ped, "USERZ", position=9, npriority=1, nsummark=287)

        model = compute_consent_model()
        self.assertIn("USERZ", model["enrollment_by_direction"][str(pediatric_ped.id)])
        self.assertEqual(model["consent_by_abiturient"]["USERZ"], pediatric.id)

        user = User.objects.create_user(abiturient_id="USERZ", is_verified=True)
        user.applied_universities.add(almazov, pediatric)
        by_uni = {row.university_name: row for row in get_user_consent_projection(user, model)}
        self.assertEqual(by_uni[PEDIATRIC_NAME].status, "admitted")
        self.assertEqual(by_uni[ALMAZOV_NAME].status, "consent_other_university")
        almazov_row = by_uni[ALMAZOV_NAME]
        self.assertEqual(almazov_row.submission_position, 35)
        self.assertLess(almazov_row.competitive_position, almazov_row.seats)
        self.assertNotEqual(almazov_row.position, almazov_row.submission_position)
        self.assertTrue(almazov_row.is_hypothetical_competitive)
        self.assertEqual(almazov_row.position_label, "прогнозный конкурсный")
        self.assertTrue(almazov_row.passes_enrollment)

    def test_user_projection_shows_hypothetical_competitive_when_locked_out(self):
        pediatric = MedicalUniversity.objects.create(name=PEDIATRIC_NAME, city=MedicalUniversity.City.SPB)
        szgmu = MedicalUniversity.objects.create(name=SZGMU_NAME, city=MedicalUniversity.City.SPB)
        pediatric_ped = StudyDirection.objects.create(
            university=pediatric,
            name="Педиатрия",
            filter_params={},
            seats=201,
        )
        szgmu_lech = StudyDirection.objects.create(
            university=szgmu,
            name="Лечебное дело",
            filter_params={},
            seats=97,
        )

        for index in range(1, 98):
            self._create_profile(
                szgmu_lech,
                f"SZ{index}",
                position=index,
                npriority=1,
                nsummark=270,
            )
        self._create_profile(pediatric_ped, "USERW", position=9, npriority=1, nsummark=290)
        self._create_profile(szgmu_lech, "USERW", position=254, npriority=1, nsummark=280)

        user = User.objects.create_user(abiturient_id="USERW", is_verified=True)
        user.applied_universities.add(pediatric, szgmu)

        model = compute_consent_model()
        self.assertNotIn("USERW", model["competitive_by_direction"].get(str(szgmu_lech.id), []))

        by_uni = {row.university_name: row for row in get_user_consent_projection(user, model)}
        szgmu_row = by_uni[SZGMU_NAME]

        self.assertEqual(szgmu_row.status, "consent_other_university")
        self.assertEqual(szgmu_row.submission_position, 254)
        self.assertLessEqual(szgmu_row.competitive_position, szgmu_row.seats)
        self.assertNotEqual(szgmu_row.position, szgmu_row.submission_position)
        self.assertTrue(szgmu_row.is_hypothetical_competitive)
        self.assertEqual(szgmu_row.position_label, "прогнозный конкурсный")
        self.assertTrue(szgmu_row.passes_enrollment)

    def test_sechenov_enrollment_excludes_from_lower_universities(self):
        sechenov = MedicalUniversity.objects.create(name=SECHENOV_NAME, city=MedicalUniversity.City.MSK)
        first_med = MedicalUniversity.objects.create(name=FIRST_MED_NAME, city=MedicalUniversity.City.SPB)
        sechenov_lech = StudyDirection.objects.create(
            university=sechenov,
            name="Лечебное дело",
            filter_params={},
            seats=1,
        )
        first_med_lech = StudyDirection.objects.create(
            university=first_med,
            name="Лечебное дело",
            filter_params={},
            seats=1,
        )

        self._create_profile(sechenov_lech, "A4", position=1, npriority=1, nsummark=300)
        self._create_profile(first_med_lech, "A4", position=1, npriority=1, nsummark=300)

        model = compute_consent_model()
        self.assertEqual(model["consent_by_abiturient"]["A4"], sechenov.id)
        self.assertNotIn("A4", model["competitive_by_direction"].get(str(first_med_lech.id), []))

    def test_tie_break_by_submission_position_in_competitive_list(self):
        university = MedicalUniversity.objects.create(name=FIRST_MED_NAME, city=MedicalUniversity.City.SPB)
        lech = StudyDirection.objects.create(
            university=university,
            name="Лечебное дело",
            filter_params={},
            seats=2,
        )

        self._create_profile(lech, "T1", position=2, npriority=1, nsummark=300)
        self._create_profile(lech, "T2", position=1, npriority=1, nsummark=300)

        model = compute_consent_model()
        competitive = model["competitive_by_direction"][str(lech.id)]
        self.assertEqual(competitive[:2], ["T2", "T1"])

    def test_olympiad_ranks_first_in_competitive_list(self):
        university = MedicalUniversity.objects.create(name=FIRST_MED_NAME, city=MedicalUniversity.City.SPB)
        lech = StudyDirection.objects.create(
            university=university,
            name="Лечебное дело",
            filter_params={},
            seats=2,
        )

        self._create_profile(lech, "REG1", position=2, npriority=1, nsummark=310)
        self._create_profile(
            lech,
            "OLY1",
            position=3,
            npriority=1,
            nsummark=0,
            raw_data={"noExam": True},
        )

        model = compute_consent_model()
        competitive = model["competitive_by_direction"][str(lech.id)]
        self.assertEqual(competitive[0], "OLY1")

    def test_cutoff_score_is_last_enrolled_applicant(self):
        university = MedicalUniversity.objects.create(name=FIRST_MED_NAME, city=MedicalUniversity.City.SPB)
        lech = StudyDirection.objects.create(
            university=university,
            name="Лечебное дело",
            filter_params={},
            seats=2,
        )

        self._create_profile(lech, "E1", position=1, npriority=1, nsummark=320)
        self._create_profile(lech, "E2", position=2, npriority=1, nsummark=310)
        self._create_profile(lech, "E3", position=3, npriority=1, nsummark=300)

        model = compute_consent_model()
        cutoff = next(item for item in model["cutoff_scores"] if item["direction_id"] == lech.id)
        self.assertEqual(cutoff["enrolled_count"], 2)
        self.assertEqual(cutoff["cutoff_score"], 310)

    def test_user_projection_for_applied_directions(self):
        university = MedicalUniversity.objects.create(name=FIRST_MED_NAME, city=MedicalUniversity.City.SPB)
        lech = StudyDirection.objects.create(
            university=university,
            name="Лечебное дело",
            filter_params={},
            seats=2,
        )

        self._create_profile(lech, "USER1", position=1, npriority=1, nsummark=320)
        self._create_profile(lech, "OTHER1", position=2, npriority=1, nsummark=310)
        self._create_profile(lech, "OTHER2", position=3, npriority=1, nsummark=300)

        user = User.objects.create_user(abiturient_id="USER1", is_verified=True)
        user.applied_universities.add(university)

        model = compute_consent_model()
        projection = get_user_consent_projection(user, model)
        self.assertEqual(len(projection), 1)
        self.assertTrue(projection[0].is_admitted)
        self.assertEqual(projection[0].position, 1)

        user2 = User.objects.create_user(abiturient_id="OTHER2", is_verified=True)
        user2.applied_universities.add(university)
        projection2 = get_user_consent_projection(user2, model)
        self.assertFalse(projection2[0].is_admitted)
        self.assertEqual(projection2[0].competitive_position, 3)
        self.assertEqual(projection2[0].status, "not_admitted")

    def test_user_projection_shows_consent_other_university(self):
        pediatric = MedicalUniversity.objects.create(name=PEDIATRIC_NAME, city=MedicalUniversity.City.SPB)
        first_med = MedicalUniversity.objects.create(name=FIRST_MED_NAME, city=MedicalUniversity.City.SPB)
        pediatric_ped = StudyDirection.objects.create(
            university=pediatric,
            name="Педиатрия",
            filter_params={},
            seats=10,
        )
        first_med_lech = StudyDirection.objects.create(
            university=first_med,
            name="Лечебное дело",
            filter_params={},
            seats=10,
        )

        for index in range(1, 11):
            self._create_profile(
                first_med_lech,
                f"FM{index}",
                position=index,
                npriority=1,
                nsummark=295,
            )
        self._create_profile(pediatric_ped, "USERX", position=1, npriority=1, nsummark=290)
        self._create_profile(first_med_lech, "USERX", position=20, npriority=2, nsummark=287)

        user = User.objects.create_user(abiturient_id="USERX", is_verified=True)
        user.applied_universities.add(pediatric, first_med)

        model = compute_consent_model()
        by_uni = {row.university_name: row for row in get_user_consent_projection(user, model)}

        self.assertEqual(by_uni[PEDIATRIC_NAME].status, "admitted")
        self.assertEqual(by_uni[FIRST_MED_NAME].status, "consent_other_university")
        self.assertEqual(by_uni[FIRST_MED_NAME].submission_position, 20)
        self.assertEqual(by_uni[FIRST_MED_NAME].competitive_position, 11)
        self.assertFalse(by_uni[FIRST_MED_NAME].is_admitted)

    def test_user_projection_shows_enrolled_on_other_direction(self):
        pediatric = MedicalUniversity.objects.create(name=PEDIATRIC_NAME, city=MedicalUniversity.City.SPB)
        pediatric_lech = StudyDirection.objects.create(
            university=pediatric,
            name="Лечебное дело",
            filter_params={},
            seats=52,
        )
        pediatric_ped = StudyDirection.objects.create(
            university=pediatric,
            name="Педиатрия",
            filter_params={},
            seats=201,
        )

        self._create_profile(pediatric_lech, "USERY", position=14, npriority=2, nsummark=290)
        self._create_profile(pediatric_ped, "USERY", position=9, npriority=1, nsummark=290)

        user = User.objects.create_user(abiturient_id="USERY", is_verified=True)
        user.applied_universities.add(pediatric)

        model = compute_consent_model()
        by_direction = {row.direction_name: row for row in get_user_consent_projection(user, model)}

        self.assertEqual(by_direction["Педиатрия"].status, "admitted")
        self.assertEqual(by_direction["Лечебное дело"].status, "admitted_other_direction")
        self.assertIn("Педиатрия", by_direction["Лечебное дело"].status_label)

    def test_passes_enrollment_true_when_competitive_within_seats_despite_other_consent(self):
        pediatric = MedicalUniversity.objects.create(name=PEDIATRIC_NAME, city=MedicalUniversity.City.SPB)
        first_med = MedicalUniversity.objects.create(name=FIRST_MED_NAME, city=MedicalUniversity.City.SPB)
        pediatric_ped = StudyDirection.objects.create(
            university=pediatric,
            name="Педиатрия",
            filter_params={},
            seats=10,
        )
        first_med_lech = StudyDirection.objects.create(
            university=first_med,
            name="Лечебное дело",
            filter_params={},
            seats=10,
        )

        for index in range(1, 6):
            self._create_profile(
                first_med_lech,
                f"FM{index}",
                position=index,
                npriority=1,
                nsummark=295,
            )
        self._create_profile(pediatric_ped, "USERX", position=1, npriority=1, nsummark=290)
        self._create_profile(first_med_lech, "USERX", position=7, npriority=2, nsummark=287)

        user = User.objects.create_user(abiturient_id="USERX", is_verified=True)
        user.applied_universities.add(pediatric, first_med)

        model = compute_consent_model()
        by_uni = {row.university_name: row for row in get_user_consent_projection(user, model)}

        self.assertEqual(by_uni[FIRST_MED_NAME].status, "admitted")
        self.assertEqual(by_uni[PEDIATRIC_NAME].status, "consent_other_university")
        self.assertTrue(by_uni[PEDIATRIC_NAME].passes_enrollment)

    def test_hypothetical_consent_projection_for_non_applied_universities(self):
        university = MedicalUniversity.objects.create(name=FIRST_MED_NAME, city=MedicalUniversity.City.SPB)
        other = MedicalUniversity.objects.create(name=SECHENOV_NAME, city=MedicalUniversity.City.MSK)
        lech = StudyDirection.objects.create(
            university=university,
            name="Лечебное дело",
            filter_params={},
            seats=2,
        )
        other_lech = StudyDirection.objects.create(
            university=other,
            name="Лечебное дело",
            filter_params={},
            seats=2,
        )

        self._create_profile(lech, "USERH", position=1, npriority=1, nsummark=320)
        self._create_profile(other_lech, "OTHER1", position=1, npriority=1, nsummark=330)
        self._create_profile(other_lech, "OTHER2", position=2, npriority=1, nsummark=310)

        user = User.objects.create_user(abiturient_id="USERH", is_verified=True)
        user.applied_universities.add(university)

        model = compute_consent_model()
        projection = get_user_hypothetical_consent_projection(user, model)
        self.assertEqual(len(projection), 1)
        self.assertEqual(projection[0].university_name, SECHENOV_NAME)
        self.assertEqual(projection[0].status_label, "Прогноз")
        self.assertEqual(projection[0].competitive_position, 2)
        self.assertTrue(projection[0].is_hypothetical_competitive)
        self.assertEqual(projection[0].position_label, "прогнозный конкурсный")
        self.assertTrue(projection[0].passes_enrollment)

    def test_analytics_snapshot_includes_consent_modeling(self):
        university = MedicalUniversity.objects.create(name=FIRST_MED_NAME, city=MedicalUniversity.City.SPB)
        lech = StudyDirection.objects.create(
            university=university,
            name="Лечебное дело",
            filter_params={},
            seats=1,
        )
        self._create_profile(lech, "X1", position=1, npriority=1, nsummark=300)

        payload = save_analytics_snapshot()
        self.assertIn("consent_modeling", payload)
        self.assertIn("cutoff_scores", payload["consent_modeling"])


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
