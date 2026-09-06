import hashlib
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from clubs.models import Club


class UiTestDataCommandTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='preserved-admin', password='password', role='admin',
        )
        self.password_fingerprint = hashlib.sha256(
            self.admin.password.encode(),
        ).hexdigest()

    def test_dataset_is_valid_identifiable_and_reversible(self):
        output = StringIO()
        call_command('ui_test_data', 'create', stdout=output)

        test_users = User.objects.filter(username__startswith='ui8_')
        test_clubs = Club.objects.filter(code__startswith='UI8C')
        self.assertEqual(test_users.count(), 100)
        self.assertEqual(test_users.filter(role__in=['student', 'president']).count(), 85)
        self.assertEqual(test_users.filter(role='teacher').count(), 15)
        self.assertEqual(test_users.filter(role='president').count(), 10)
        self.assertEqual(test_users.filter(club__isnull=False).count(), 73)
        self.assertEqual(
            test_users.filter(role__in=['student', 'president'], club__isnull=True).count(),
            12,
        )
        self.assertEqual(test_clubs.count(), 10)
        self.assertEqual(test_clubs.exclude(teacher='').count(), 10)
        self.assertTrue(any(
            club.current_members == club.max_members for club in test_clubs
        ))

        self.client.force_login(self.admin)
        account_page = self.client.get(reverse('account_admin_list'))
        self.assertEqual(account_page.status_code, 200)
        self.assertContains(account_page, '1 / 2')
        self.assertContains(account_page, 'for="account-search"')
        self.assertContains(account_page, 'for="account-role-filter"')

        with CaptureQueriesContext(connection) as account_queries:
            self.client.get(reverse('account_admin_list'))
        self.assertLessEqual(len(account_queries), 11)

        teacher_filter = self.client.get(
            reverse('account_admin_list'), {'role': 'teacher'},
        )
        self.assertEqual(teacher_filter.status_code, 200)
        self.assertEqual(teacher_filter.context['paginator'].count, 15)
        self.assertEqual(teacher_filter.context['selected_role'], 'teacher')

        searched_page_two = self.client.get(
            reverse('account_admin_list'), {'q': 'UI8', 'page': 2},
        )
        self.assertEqual(searched_page_two.status_code, 200)
        self.assertEqual(searched_page_two.context['page_obj'].number, 2)

        student_page_two = self.client.get(
            reverse('student_admin_list'), {'page': 2},
        )
        self.assertEqual(student_page_two.status_code, 200)
        self.assertContains(student_page_two, '2 / 2')

        long_value_search = self.client.get(
            reverse('student_admin_list'), {'q': 'Intentionally Long'},
        )
        self.assertEqual(long_value_search.status_code, 200)
        self.assertContains(long_value_search, 'UI8 Test Student 017')

        with CaptureQueriesContext(connection) as club_queries:
            club_response = self.client.get(reverse('club_list'))
        self.assertEqual(club_response.status_code, 200)
        self.assertLessEqual(len(club_queries), 6)

        with CaptureQueriesContext(connection) as teacher_queries:
            teacher_response = self.client.get(reverse('teacher_admin_list'))
        self.assertEqual(teacher_response.status_code, 200)
        self.assertLessEqual(len(teacher_queries), 7)

        call_command('ui_test_data', 'remove', stdout=output)

        self.assertFalse(User.objects.filter(username__startswith='ui8_').exists())
        self.assertFalse(Club.objects.filter(code__startswith='UI8C').exists())
        self.admin.refresh_from_db()
        self.assertEqual(
            hashlib.sha256(self.admin.password.encode()).hexdigest(),
            self.password_fingerprint,
        )
        self.assertTrue(self.admin.is_active)
        self.assertTrue(self.admin.is_staff)
        self.assertTrue(self.admin.is_superuser)


class ResponsiveAccessibilityContractTests(SimpleTestCase):
    def read_project_file(self, relative_path):
        return (Path(settings.BASE_DIR) / relative_path).read_text(encoding='utf-8')

    def test_mobile_touch_dialog_and_progress_rules_are_present(self):
        css = self.read_project_file('static/css/design-system.css')
        self.assertIn('@media (max-width: 575.98px)', css)
        self.assertIn('min-height: 2.75rem;', css)
        self.assertIn('max-height: calc(100dvh - (var(--space-3) * 2));', css)
        self.assertIn('.dashboard-progress {', css)
        self.assertIn('grid-template-columns: 1fr;', css)
        self.assertIn('@media (prefers-reduced-motion: reduce)', css)
        self.assertIn('--color-focus: #3158c9;', css)

    def test_workflow_modals_have_programmatic_names(self):
        for relative_path in [
            'templates/transfers/pending_approvals.html',
            'templates/transfers/all_requests.html',
        ]:
            template = self.read_project_file(relative_path)
            self.assertIn('aria-modal="true"', template)
            self.assertIn('aria-labelledby=', template)

    def test_primary_pages_and_search_controls_have_semantics(self):
        expected = {
            'templates/base.html': 'href="#main-content"',
            'templates/accounts/login.html': '<h1',
            'templates/accounts/profile.html': '<h1',
            'templates/clubs/club_detail.html': '<h1',
            'templates/transfers/request_detail.html': '<h1',
            'templates/transfers/all_requests.html': '<h1',
            'templates/accounts/account_admin_list.html': 'for="account-search"',
            'templates/accounts/student_admin_list.html': 'for="student-search"',
            'templates/accounts/teacher_admin_list.html': 'for="teacher-search"',
            'templates/accounts/club_admin_list.html': 'for="club-admin-search"',
            'templates/accounts/unassigned_account_list.html': 'for="unassigned-search"',
            'templates/clubs/club_list.html': 'for="club-search"',
        }
        for relative_path, marker in expected.items():
            self.assertIn(marker, self.read_project_file(relative_path))
