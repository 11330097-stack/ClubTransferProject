from django.test import TestCase
from django.urls import reverse

from clubs.models import Club

from .models import User


class ClubAdminDeleteViewTests(TestCase):
    def test_safe_delete_releases_accounts_and_demotes_president(self):
        admin = User.objects.create_user(
            username='admin',
            password='password',
            role='admin',
        )
        club = Club.objects.create(
            code='TEST',
            name='Test Club',
            teacher='Test Teacher',
            president='Test President (president)',
        )
        president = User.objects.create_user(
            username='president',
            role='president',
            club=club,
        )
        student = User.objects.create_user(
            username='student',
            role='student',
            club=club,
        )
        teacher = User.objects.create_user(
            username='teacher',
            role='teacher',
            club=club,
        )

        self.client.force_login(admin)
        response = self.client.post(reverse('club_admin_delete', args=[club.pk]))

        self.assertRedirects(response, reverse('club_admin_list'))

        club.refresh_from_db()
        president.refresh_from_db()
        student.refresh_from_db()
        teacher.refresh_from_db()

        self.assertFalse(club.is_active)
        self.assertEqual(club.teacher, '')
        self.assertEqual(club.president, '')
        self.assertEqual(president.role, 'student')
        self.assertIsNone(president.club)
        self.assertEqual(student.role, 'student')
        self.assertIsNone(student.club)
        self.assertEqual(teacher.role, 'teacher')
        self.assertIsNone(teacher.club)
        self.assertEqual(
            User.objects.filter(pk__in=[president.pk, student.pk, teacher.pk]).count(),
            3,
        )

        response = self.client.get(reverse('unassigned_account_list'))
        unassigned_accounts = list(response.context['accounts'])
        self.assertIn(president, unassigned_accounts)
        self.assertIn(student, unassigned_accounts)
        self.assertEqual(president.get_role_display(), '學生')

