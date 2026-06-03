from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from clubs.models import Club
from transfers.models import ApprovalLog, TransferRequest

from .forms import ClubAdminForm
from .models import User


class ClubAdminDeleteViewTests(TestCase):
    def test_club_admin_list_only_shows_edit_and_delete_for_active_clubs(self):
        admin = User.objects.create_user(
            username='admin-list',
            password='password',
            role='admin',
        )
        active_club = Club.objects.create(code='ACTIVE', name='Active Club')
        inactive_club = Club.objects.create(code='INACTIVE', name='Inactive Club', is_active=False)

        self.client.force_login(admin)
        response = self.client.get(reverse('club_admin_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, active_club.name)
        self.assertNotContains(response, inactive_club.name)
        self.assertContains(response, reverse('club_admin_edit', args=[active_club.pk]))
        self.assertContains(response, reverse('club_admin_delete', args=[active_club.pk]))
        self.assertNotContains(response, 'reactivate')
        self.assertNotContains(response, 'deactivate')

    def test_club_reactivate_and_deactivate_urls_do_not_exist(self):
        with self.assertRaises(NoReverseMatch):
            reverse('club_admin_reactivate', args=[1])
        with self.assertRaises(NoReverseMatch):
            reverse('club_admin_deactivate', args=[1])

        self.assertEqual(self.client.post('/admin-panel/clubs/1/reactivate/').status_code, 404)
        self.assertEqual(self.client.post('/admin-panel/clubs/1/deactivate/').status_code, 404)

    def test_club_admin_form_does_not_expose_is_active(self):
        self.assertNotIn('is_active', ClubAdminForm().fields)

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

        response = self.client.get(reverse('club_list'))
        self.assertNotContains(response, club.name)

        response = self.client.get(reverse('club_admin_list'))
        self.assertNotContains(response, club.name)


class StudentAdminBulkActionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin',
            password='password',
            role='admin',
        )
        self.club = Club.objects.create(code='A001', name='Club A')
        self.other_club = Club.objects.create(code='B001', name='Club B')
        self.student_one = User.objects.create_user(
            username='student-one',
            role='student',
            club=self.club,
        )
        self.student_two = User.objects.create_user(
            username='student-two',
            role='student',
            club=self.club,
        )
        self.teacher = User.objects.create_user(
            username='teacher',
            role='teacher',
            club=self.club,
        )
        self.client.force_login(self.admin)

    def test_bulk_deactivate_and_reactivate_students_only(self):
        self.club.current_members = 2
        self.club.save(update_fields=['current_members'])

        response = self.client.post(
            reverse('student_admin_bulk_deactivate'),
            {'student_ids': [self.student_one.pk, self.student_two.pk, self.teacher.pk]},
        )

        self.assertRedirects(response, reverse('student_admin_list'))
        self.student_one.refresh_from_db()
        self.student_two.refresh_from_db()
        self.teacher.refresh_from_db()
        self.club.refresh_from_db()
        self.assertFalse(self.student_one.is_active)
        self.assertFalse(self.student_two.is_active)
        self.assertTrue(self.teacher.is_active)
        self.assertEqual(self.club.current_members, 0)

        response = self.client.post(
            reverse('student_admin_bulk_reactivate'),
            {'student_ids': [self.student_one.pk, self.student_two.pk, self.teacher.pk]},
        )

        self.assertRedirects(response, reverse('student_admin_list'))
        self.student_one.refresh_from_db()
        self.student_two.refresh_from_db()
        self.teacher.refresh_from_db()
        self.club.refresh_from_db()
        self.assertTrue(self.student_one.is_active)
        self.assertTrue(self.student_two.is_active)
        self.assertTrue(self.teacher.is_active)
        self.assertEqual(self.club.current_members, 2)

    def test_bulk_delete_deletes_students_without_history_and_deactivates_history(self):
        student_without_history = User.objects.create_user(
            username='student-without-history',
            role='student',
            club=self.club,
        )
        transfer_request = TransferRequest.objects.create(
            student=self.student_two,
            original_club=self.club,
            target_club=self.other_club,
        )
        ApprovalLog.objects.create(
            transfer_request=transfer_request,
            approver=self.student_one,
            approval_stage='orig_teacher_pending',
            result='approve',
        )
        self.club.current_members = 3
        self.club.save(update_fields=['current_members'])

        response = self.client.post(
            reverse('student_admin_bulk_delete'),
            {
                'student_ids': [
                    student_without_history.pk,
                    self.student_one.pk,
                    self.student_two.pk,
                    self.teacher.pk,
                ],
            },
        )

        self.assertRedirects(response, reverse('student_admin_list'))
        self.assertFalse(User.objects.filter(pk=student_without_history.pk).exists())
        self.student_one.refresh_from_db()
        self.student_two.refresh_from_db()
        self.teacher.refresh_from_db()
        self.club.refresh_from_db()
        self.assertFalse(self.student_one.is_active)
        self.assertFalse(self.student_two.is_active)
        self.assertTrue(self.teacher.is_active)
        self.assertEqual(self.club.current_members, 0)

    def test_bulk_delete_confirm_lists_students_only(self):
        response = self.client.post(
            reverse('student_admin_bulk_delete_confirm'),
            {'student_ids': [self.student_one.pk, self.teacher.pk]},
        )

        self.assertEqual(response.status_code, 200)
        students = list(response.context['students'])
        self.assertEqual(students, [self.student_one])
        self.assertContains(response, self.student_one.username)
        self.assertNotContains(response, self.teacher.username)

    def test_non_admin_cannot_use_bulk_actions(self):
        self.client.force_login(self.student_one)

        response = self.client.post(
            reverse('student_admin_bulk_deactivate'),
            {'student_ids': [self.student_two.pk]},
        )

        self.assertEqual(response.status_code, 403)
        self.student_two.refresh_from_db()
        self.assertTrue(self.student_two.is_active)


class StudentAdminPresidentManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin-president-management',
            password='password',
            role='admin',
        )
        self.club = Club.objects.create(
            code='P001',
            name='President Club',
            president='President User (president-user)',
            current_members=1,
        )
        self.president = User.objects.create_user(
            username='president-user',
            password='password',
            role='president',
            student_id='P001',
            first_name='President User',
            club=self.club,
        )
        self.client.force_login(self.admin)

    def test_student_admin_list_shows_president(self):
        response = self.client.get(
            reverse('student_admin_list'),
            {'q': self.president.username},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.president.username)
        self.assertContains(response, '社長')
        self.assertContains(response, '降級為一般學生')

    def test_editing_president_demotes_and_clears_club_president(self):
        response = self.client.post(
            reverse('student_admin_edit', args=[self.president.pk]),
            {
                'username': self.president.username,
                'student_id': self.president.student_id,
                'class_name': '',
                'seat_number': '',
                'first_name': self.president.first_name,
                'email': '',
                'role': 'student',
                'club': self.club.pk,
                'is_active': 'on',
                'password': '',
            },
        )

        self.assertRedirects(response, reverse('student_admin_list'))
        self.president.refresh_from_db()
        self.club.refresh_from_db()
        self.assertEqual(self.president.role, 'student')
        self.assertEqual(self.club.president, '')
        self.assertEqual(self.club.current_members, 1)
