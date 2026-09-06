from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from clubs.models import Club
from transfers.models import TransferWindow

from .models import User


class NavigationShellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.club = Club.objects.create(
            code='NAV01',
            name='導覽測試社',
            location='活動中心',
            max_members=30,
        )
        cls.admin = User.objects.create_user(
            username='nav-admin',
            password='test-password',
            role='admin',
            first_name='導覽管理員',
        )
        cls.student = User.objects.create_user(
            username='nav-student',
            password='test-password',
            role='student',
            student_id='NAV001',
            first_name='導覽學生',
            club=cls.club,
        )
        cls.president = User.objects.create_user(
            username='nav-president',
            password='test-password',
            role='president',
            student_id='NAV002',
            first_name='導覽社長',
            club=cls.club,
        )
        cls.teacher = User.objects.create_user(
            username='nav-teacher',
            password='test-password',
            role='teacher',
            first_name='導覽老師',
        )
        cls.club.president = '導覽社長 (nav-president)'
        cls.club.teacher = '導覽老師 (nav-teacher)'
        cls.club.save(update_fields=['president', 'teacher'])

        today = timezone.localdate()
        TransferWindow.objects.create(
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
        )

    def get_home_as(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('home'))

    def test_admin_navigation_contains_only_admin_and_review_destinations(self):
        response = self.get_home_as(self.admin)

        self.assertContains(response, 'class="app-shell"')
        self.assertContains(response, reverse('pending_approvals'))
        self.assertContains(response, reverse('all_requests'))
        self.assertContains(response, reverse('transfer_record_archive_list'))
        self.assertContains(response, reverse('transfer_window_settings'))
        self.assertContains(response, reverse('club_admin_list'))
        self.assertContains(response, reverse('unassigned_account_list'))
        self.assertContains(response, reverse('account_admin_list'))
        self.assertNotContains(response, reverse('transfer_apply'))
        self.assertNotContains(response, reverse('my_requests'))

    def test_student_navigation_contains_student_destinations_only(self):
        response = self.get_home_as(self.student)

        self.assertContains(response, reverse('transfer_apply'))
        self.assertContains(response, reverse('my_requests'))
        self.assertNotContains(response, reverse('pending_approvals'))
        self.assertNotContains(response, reverse('all_requests'))
        self.assertNotContains(response, reverse('account_admin_list'))

    def test_president_and_teacher_navigation_exposes_review_not_admin_tools(self):
        for user in (self.president, self.teacher):
            with self.subTest(role=user.role):
                response = self.get_home_as(user)
                self.assertContains(response, reverse('pending_approvals'))
                self.assertNotContains(response, reverse('transfer_apply'))
                self.assertNotContains(response, reverse('my_requests'))
                self.assertNotContains(response, reverse('all_requests'))
                self.assertNotContains(response, reverse('account_admin_list'))

    def test_active_navigation_is_semantic(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('account_admin_list'))

        self.assertContains(
            response,
            f'href="{reverse("account_admin_list")}" '
            'class="app-nav-link active" aria-current="page"',
        )

    def test_mobile_navigation_and_account_actions_are_available(self):
        response = self.get_home_as(self.student)

        self.assertContains(response, 'id="mobileNavigation"')
        self.assertContains(response, 'aria-label="開啟導覽選單"')
        self.assertContains(response, reverse('profile'))
        self.assertContains(response, reverse('logout'))
