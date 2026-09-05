from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from clubs.models import Club
from transfers.models import TransferRequest
from .models import User


def csv_upload(content):
    return SimpleUploadedFile('audit.csv', content.encode('utf-8'), content_type='text/csv')


class AccountAndClubInvariantTests(TestCase):
    password = 'Valid-Audit-937!'

    def setUp(self):
        self.admin = User.objects.create_user(
            username='audit-admin', password=self.password, role='admin'
        )
        self.client.force_login(self.admin)

    def make_active_club(self, code='AUD1', max_members=30):
        president = User.objects.create_user(
            username=f'{code.lower()}-president',
            student_id=f'{code.lower()}-president',
            password=self.password,
            role='president',
            is_active=True,
        )
        club = Club.objects.create(
            code=code,
            name=f'{code} Club',
            president=f'President ({president.username})',
            max_members=max_members,
            current_members=1,
            is_active=True,
        )
        president.club = club
        president.save(update_fields=['club'])
        return club, president

    def test_active_president_cannot_be_deactivated_without_replacement(self):
        club, president = self.make_active_club()

        response = self.client.post(
            reverse('student_admin_deactivate', args=[president.pk]),
            follow=True,
        )

        president.refresh_from_db()
        club.refresh_from_db()
        self.assertTrue(president.is_active)
        self.assertEqual(president.role, 'president')
        self.assertEqual(president.club, club)
        self.assertIn(f'({president.username})', club.president)
        self.assertContains(response, '社長交接', status_code=200)

    def test_deleting_inactive_legacy_president_clears_exact_text_reference(self):
        club = Club.objects.create(
            code='AUD1B', name='Inactive Legacy Club', is_active=False,
            president='legacy-president',
        )
        president = User.objects.create_user(
            username='legacy-president', student_id='legacy-president',
            password=self.password, role='president', club=club, is_active=True,
        )

        self.client.post(reverse('student_admin_delete', args=[president.pk]))

        club.refresh_from_db()
        self.assertFalse(User.objects.filter(pk=president.pk).exists())
        self.assertEqual(club.president, '')

    def test_reactivation_requires_a_valid_active_president(self):
        club = Club.objects.create(code='AUD2', name='Inactive Club', is_active=False)

        self.client.post(reverse('club_admin_reactivate', args=[club.pk]))

        club.refresh_from_db()
        self.assertFalse(club.is_active)

    def test_reactivation_requires_and_accepts_valid_president_and_teacher(self):
        club = Club.objects.create(code='AUD2B', name='Inactive Club', is_active=False)
        president = User.objects.create_user(
            username='reactivation-president', student_id='reactivation-president',
            password=self.password, role='president', club=club, is_active=True,
        )
        teacher = User.objects.create_user(
            username='reactivation-teacher', password=self.password,
            role='teacher', is_active=True,
        )
        club.president = f'President ({president.username})'
        club.save(update_fields=['president'])

        self.client.post(reverse('club_admin_reactivate', args=[club.pk]))
        club.refresh_from_db()
        self.assertFalse(club.is_active)

        club.teacher = f'Teacher ({teacher.username})'
        club.save(update_fields=['teacher'])
        self.client.post(reverse('club_admin_reactivate', args=[club.pk]))
        club.refresh_from_db()
        self.assertTrue(club.is_active)

    def test_deactivating_club_terminates_related_active_transfers(self):
        original, _ = self.make_active_club(code='AUD2C')
        target, _ = self.make_active_club(code='AUD2D')
        student = User.objects.create_user(
            username='deactivation-transfer', student_id='deactivation-transfer',
            password=self.password, role='student', club=original, is_active=True,
        )
        transfer_request = TransferRequest.objects.create(
            student=student, original_club=original, target_club=target,
            status='new_president_pending',
        )

        self.client.post(reverse('club_admin_deactivate', args=[target.pk]))

        transfer_request.refresh_from_db()
        student.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(transfer_request.status, 'rejected')
        self.assertIsNotNone(transfer_request.completed_at)
        self.assertEqual(student.club, original)
        self.assertFalse(target.is_active)

    def test_account_creation_uses_actual_membership_for_capacity(self):
        club, _ = self.make_active_club(code='AUD3', max_members=1)
        club.current_members = 0
        club.save(update_fields=['current_members'])

        response = self.client.post(reverse('account_admin_create'), {
            'role': 'student', 'login_id': 'capacity-student', 'first_name': 'Capacity',
            'email': '', 'class_name': '', 'seat_number': '', 'club': club.pk,
            'password': self.password, 'password_confirm': self.password,
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='capacity-student').exists())

    def test_student_edit_cannot_move_into_a_full_club(self):
        source, _ = self.make_active_club(code='AUD4')
        target, _ = self.make_active_club(code='AUD5', max_members=1)
        target.current_members = 0
        target.save(update_fields=['current_members'])
        student = User.objects.create_user(
            username='moving-student', student_id='moving-student', password=self.password,
            role='student', club=source, is_active=True,
        )

        response = self.client.post(reverse('student_admin_edit', args=[student.pk]), {
            'student_id': student.student_id, 'class_name': '', 'seat_number': '',
            'first_name': 'Moving', 'email': '', 'role': 'student', 'club': target.pk,
            'is_active': 'on', 'password': '', 'password_confirm': '',
        })

        self.assertEqual(response.status_code, 200)
        student.refresh_from_db()
        self.assertEqual(student.club, source)

    def test_club_form_cannot_lower_capacity_below_actual_members(self):
        club, president = self.make_active_club(code='AUD6', max_members=5)
        teacher = User.objects.create_user(
            username='capacity-teacher', password=self.password, role='teacher', is_active=True
        )
        User.objects.create_user(
            username='capacity-member', student_id='capacity-member', password=self.password,
            role='student', club=club, is_active=True,
        )

        response = self.client.post(reverse('club_admin_edit', args=[club.pk]), {
            'code': club.code, 'name': club.name, 'teacher': teacher.pk,
            'president': president.pk, 'location': '', 'description': '', 'max_members': 1,
        })

        self.assertEqual(response.status_code, 200)
        club.refresh_from_db()
        self.assertEqual(club.max_members, 5)

    def test_club_csv_requires_president_and_preserves_existing_club(self):
        club, president = self.make_active_club(code='AUD7')
        content = (
            'code,name,teacher_username,president_username,location,max_members\n'
            'AUD7,Changed Club,,,Room,30\n'
        )

        response = self.client.post(
            reverse('club_admin_import'), {'csv_file': csv_upload(content)}
        )

        club.refresh_from_db()
        president.refresh_from_db()
        self.assertEqual(response.context['result']['skipped'], 1)
        self.assertEqual(club.name, 'AUD7 Club')
        self.assertEqual(president.role, 'president')
        self.assertEqual(president.club, club)

    def test_account_csv_cannot_reassign_an_existing_president(self):
        club, president = self.make_active_club(code='AUD8')
        content = (
            'role,login_id,name,email,class_name,seat_number,club_name,password\n'
            f'student,{president.username},Changed President,,,,,\n'
        )

        response = self.client.post(
            reverse('account_admin_import'), {'csv_file': csv_upload(content)}
        )

        president.refresh_from_db()
        club.refresh_from_db()
        self.assertEqual(response.context['result']['skipped'], 1)
        self.assertEqual(president.role, 'president')
        self.assertEqual(president.club, club)
        self.assertIn(f'({president.username})', club.president)

    def test_teacher_edit_synchronizes_or_clears_club_reference(self):
        teacher = User.objects.create_user(
            username='old-teacher', password=self.password, role='teacher',
            first_name='Teacher', is_active=True,
        )
        club, _ = self.make_active_club(code='AUD9')
        club.teacher = 'Teacher (old-teacher)'
        club.save(update_fields=['teacher'])

        response = self.client.post(reverse('teacher_admin_edit', args=[teacher.pk]), {
            'username': 'new-teacher', 'first_name': 'Teacher', 'email': '',
            'is_active': 'on', 'password': '', 'password_confirm': '',
        })

        self.assertEqual(response.status_code, 302)
        club.refresh_from_db()
        self.assertEqual(club.teacher, 'Teacher (new-teacher)')

        response = self.client.post(reverse('teacher_admin_edit', args=[teacher.pk]), {
            'username': 'new-teacher', 'first_name': 'Teacher', 'email': '',
            'password': '', 'password_confirm': '',
        })
        self.assertEqual(response.status_code, 302)
        club.refresh_from_db()
        self.assertEqual(club.teacher, '')

    def test_inactive_student_or_inactive_club_cannot_be_promoted(self):
        club, _ = self.make_active_club(code='AUD10')
        inactive = User.objects.create_user(
            username='inactive-candidate', student_id='inactive-candidate',
            password=self.password, role='student', club=club, is_active=False,
        )
        response = self.client.post(
            reverse('student_admin_promote_president', args=[inactive.pk])
        )
        self.assertEqual(response.status_code, 302)
        inactive.refresh_from_db()
        self.assertEqual(inactive.role, 'student')

        club.is_active = False
        club.save(update_fields=['is_active'])
        active = User.objects.create_user(
            username='inactive-club-candidate', student_id='inactive-club-candidate',
            password=self.password, role='student', club=club, is_active=True,
        )
        self.client.post(reverse('student_admin_promote_president', args=[active.pk]))
        active.refresh_from_db()
        self.assertEqual(active.role, 'student')

    def test_student_with_pending_transfer_cannot_be_promoted(self):
        original, _ = self.make_active_club(code='AUD11')
        target, _ = self.make_active_club(code='AUD12')
        student = User.objects.create_user(
            username='pending-candidate', student_id='pending-candidate', password=self.password,
            role='student', club=original, is_active=True,
        )
        TransferRequest.objects.create(
            student=student, original_club=original, target_club=target,
            status='orig_president_pending',
        )

        self.client.post(reverse('student_admin_promote_president', args=[student.pk]))

        student.refresh_from_db()
        self.assertEqual(student.role, 'student')

    def test_pending_transfer_blocks_student_deactivation_and_club_edit(self):
        original, _ = self.make_active_club(code='AUD13')
        target, _ = self.make_active_club(code='AUD14')
        student = User.objects.create_user(
            username='pending-edit', student_id='pending-edit', password=self.password,
            role='student', club=original, is_active=True,
        )
        TransferRequest.objects.create(
            student=student, original_club=original, target_club=target,
            status='orig_president_pending',
        )

        self.client.post(reverse('student_admin_deactivate', args=[student.pk]))
        student.refresh_from_db()
        self.assertTrue(student.is_active)

        response = self.client.post(reverse('student_admin_edit', args=[student.pk]), {
            'student_id': student.student_id, 'class_name': '', 'seat_number': '',
            'first_name': 'Pending', 'email': '', 'role': 'student', 'club': target.pk,
            'is_active': 'on', 'password': '', 'password_confirm': '',
        })
        self.assertEqual(response.status_code, 200)
        student.refresh_from_db()
        self.assertEqual(student.club, original)

    def test_account_csv_rejects_duplicate_rows(self):
        content = (
            'role,login_id,name,email,class_name,seat_number,club_name,password\n'
            f'teacher,duplicate-row,First,,,,,{self.password}\n'
            'teacher,duplicate-row,Second,,,,,\n'
        )

        response = self.client.post(
            reverse('account_admin_import'), {'csv_file': csv_upload(content)}
        )

        result = response.context['result']
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(User.objects.get(username='duplicate-row').first_name, 'First')

    def test_account_csv_uses_actual_membership_for_capacity(self):
        club, _ = self.make_active_club(code='AUD15', max_members=1)
        club.current_members = 0
        club.save(update_fields=['current_members'])
        content = (
            'role,login_id,name,email,class_name,seat_number,club_name,password\n'
            f'student,csv-capacity,CSV Capacity,,,1,{club.name},{self.password}\n'
        )

        response = self.client.post(
            reverse('account_admin_import'), {'csv_file': csv_upload(content)}
        )

        result = response.context['result']
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['skipped'], 1)
        self.assertFalse(User.objects.filter(username='csv-capacity').exists())

    def test_database_rejects_case_insensitive_duplicate_login_ids(self):
        User.objects.create_user(username='CaseLogin', password=self.password, role='teacher')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(
                    username='caselogin', password=self.password, role='teacher'
                )


class BuiltInAdminSafetyTests(TestCase):
    password = 'Valid-Admin-937!'

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='django-admin', email='admin@example.test', password=self.password
        )
        self.student = User.objects.create_user(
            username='admin-path-student', student_id='admin-path-student',
            password=self.password, role='student', is_active=True,
        )
        self.club = Club.objects.create(code='ADM1', name='Admin Path Club')
        self.client.force_login(self.superuser)

    def test_generic_user_admin_cannot_bypass_project_account_workflow(self):
        self.assertEqual(self.client.get(reverse('admin:accounts_user_add')).status_code, 403)
        change_url = reverse('admin:accounts_user_change', args=[self.student.pk])
        response = self.client.post(change_url, {
            'username': 'bypassed-student', 'role': 'teacher',
            'date_joined_0': '2026-09-05', 'date_joined_1': '00:00:00',
        })
        self.assertEqual(response.status_code, 403)
        self.student.refresh_from_db()
        self.assertEqual(self.student.username, 'admin-path-student')
        self.assertEqual(self.student.role, 'student')
        self.assertEqual(
            self.client.get(
                reverse('admin:accounts_user_delete', args=[self.student.pk])
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse('admin:accounts_user_change', args=[self.superuser.pk])
            ).status_code,
            200,
        )

    def test_generic_club_admin_cannot_bypass_project_club_workflow(self):
        self.assertEqual(self.client.get(reverse('admin:clubs_club_add')).status_code, 403)
        response = self.client.post(
            reverse('admin:clubs_club_change', args=[self.club.pk]),
            {'name': 'Bypassed Club', 'is_active': 'on'},
        )
        self.assertEqual(response.status_code, 403)
        self.club.refresh_from_db()
        self.assertEqual(self.club.name, 'Admin Path Club')
        self.assertEqual(
            self.client.get(reverse('admin:clubs_club_delete', args=[self.club.pk])).status_code,
            403,
        )
