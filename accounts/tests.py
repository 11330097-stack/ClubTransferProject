from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import authenticate
from django.test import TestCase
from django.urls import reverse

from clubs.models import Club
from transfers.models import ApprovalLog, TransferRequest

from .forms import ClubAdminForm
from .models import User


def csv_upload(content):
    return SimpleUploadedFile(
        'import.csv',
        content.encode('utf-8'),
        content_type='text/csv',
    )


def uploaded_file(name, content, content_type='application/octet-stream'):
    if isinstance(content, str):
        content = content.encode('utf-8')
    return SimpleUploadedFile(name, content, content_type=content_type)


class ClubAdminDeleteViewTests(TestCase):
    def test_club_admin_list_shows_active_and_inactive_clubs_with_state_actions(self):
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
        self.assertContains(response, inactive_club.name)
        self.assertContains(response, reverse('club_admin_edit', args=[active_club.pk]))
        self.assertContains(response, reverse('club_admin_delete', args=[active_club.pk]))
        self.assertContains(response, reverse('club_admin_reactivate', args=[inactive_club.pk]))
        self.assertContains(response, reverse('club_admin_deactivate', args=[active_club.pk]))

    def test_club_reactivate_and_deactivate_urls_exist(self):
        self.assertEqual(reverse('club_admin_reactivate', args=[1]), '/admin-panel/clubs/1/reactivate/')
        self.assertEqual(reverse('club_admin_deactivate', args=[1]), '/admin-panel/clubs/1/deactivate/')

    def test_club_admin_form_does_not_expose_is_active(self):
        self.assertNotIn('is_active', ClubAdminForm().fields)

    def test_safe_delete_removes_club_releases_accounts_and_demotes_president(self):
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
        unrelated_user = User.objects.create_user(
            username='unrelated-student',
            role='student',
        )

        self.client.force_login(admin)
        response = self.client.post(reverse('club_admin_delete', args=[club.pk]))

        self.assertRedirects(response, reverse('club_admin_list'))

        president.refresh_from_db()
        student.refresh_from_db()
        teacher.refresh_from_db()

        self.assertFalse(Club.objects.filter(pk=club.pk).exists())
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
        self.assertTrue(User.objects.filter(pk=unrelated_user.pk).exists())

        response = self.client.get(reverse('unassigned_account_list'))
        unassigned_accounts = list(response.context['accounts'])
        self.assertIn(president, unassigned_accounts)
        self.assertIn(student, unassigned_accounts)
        self.assertEqual(president.get_role_display(), '學生')

        response = self.client.get(reverse('club_list'))
        self.assertNotContains(response, club.name)

        response = self.client.get(reverse('club_admin_list'))
        self.assertNotContains(response, club.name)

    def test_club_with_transfer_history_is_deactivated_instead_of_deleted(self):
        admin = User.objects.create_user(
            username='history-club-admin',
            password='password',
            role='admin',
        )
        original_club = Club.objects.create(code='HIST', name='History Club')
        target_club = Club.objects.create(code='HIST2', name='History Target')
        student = User.objects.create_user(
            username='history-club-student',
            role='student',
            club=original_club,
        )
        transfer_request = TransferRequest.objects.create(
            student=student,
            original_club=original_club,
            target_club=target_club,
        )

        self.client.force_login(admin)
        response = self.client.post(
            reverse('club_admin_delete', args=[original_club.pk]),
        )

        self.assertRedirects(response, reverse('club_admin_list'))
        original_club.refresh_from_db()
        student.refresh_from_db()
        self.assertFalse(original_club.is_active)
        self.assertIsNone(student.club)
        self.assertTrue(TransferRequest.objects.filter(pk=transfer_request.pk).exists())

    def test_non_admin_cannot_delete_club(self):
        club = Club.objects.create(code='DENY', name='Protected Club')
        student = User.objects.create_user(
            username='non-admin-club-delete',
            role='student',
            club=club,
        )

        self.client.force_login(student)
        response = self.client.post(reverse('club_admin_delete', args=[club.pk]))

        self.assertEqual(response.status_code, 403)
        club.refresh_from_db()
        student.refresh_from_db()
        self.assertTrue(club.is_active)
        self.assertEqual(student.club, club)

    def test_safe_delete_demotes_president_resolved_from_club_text(self):
        admin = User.objects.create_user(
            username='admin-text-president',
            password='password',
            role='admin',
        )
        club = Club.objects.create(
            code='TEXT',
            name='Text President Club',
            president='Text President (text-president)',
        )
        president = User.objects.create_user(
            username='text-president',
            first_name='Text President',
            role='president',
            club=None,
        )

        self.client.force_login(admin)
        self.client.post(reverse('club_admin_delete', args=[club.pk]))

        president.refresh_from_db()
        self.assertEqual(president.role, 'student')
        self.assertIsNone(president.club)

        response = self.client.get(reverse('unassigned_account_list'))
        self.assertIn(president, list(response.context['accounts']))


class ClubCsvImportViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='club-import-admin',
            password='password',
            role='admin',
        )
        self.teacher = User.objects.create_user(
            username='teacher-import',
            first_name='Teacher Import',
            role='teacher',
            is_active=True,
        )
        self.student = User.objects.create_user(
            username='student-import',
            first_name='Student Import',
            role='student',
            is_active=True,
            club=None,
        )

    def test_club_admin_list_links_to_import(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('club_admin_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('club_admin_import'))
        self.assertContains(response, '匯入社團 CSV')

    def test_non_admin_cannot_import_clubs(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse('club_admin_import'))

        self.assertEqual(response.status_code, 403)

    def test_import_creates_club_and_assigns_teacher_and_president(self):
        self.client.force_login(self.admin)
        content = (
            'code,name,teacher_username,president_username,location,max_members,description\n'
            'C001,CSV Club,teacher-import,student-import,Room 1,35,Imported club\n'
        )

        response = self.client.post(
            reverse('club_admin_import'),
            {'csv_file': csv_upload(content)},
        )

        self.assertEqual(response.status_code, 200)
        result = response.context['result']
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['updated'], 0)
        self.assertEqual(result['skipped'], 0)

        club = Club.objects.get(code='C001')
        self.student.refresh_from_db()
        self.assertEqual(club.name, 'CSV Club')
        self.assertEqual(club.teacher, 'Teacher Import (teacher-import)')
        self.assertEqual(club.president, 'Student Import (student-import)')
        self.assertEqual(club.location, 'Room 1')
        self.assertEqual(club.max_members, 35)
        self.assertEqual(club.description, 'Imported club')
        self.assertEqual(club.current_members, 1)
        self.assertEqual(self.student.role, 'president')
        self.assertEqual(self.student.club, club)

    def test_import_updates_existing_club_and_replaces_president(self):
        self.client.force_login(self.admin)
        club = Club.objects.create(
            code='C002',
            name='Old Club',
            president='Old President (old-president)',
        )
        old_president = User.objects.create_user(
            username='old-president',
            first_name='Old President',
            role='president',
            is_active=True,
            club=club,
        )
        content = (
            'code,name,teacher_username,president_username,location,max_members\n'
            'C002,Updated Club,teacher-import,student-import,Room 2,20\n'
        )

        response = self.client.post(
            reverse('club_admin_import'),
            {'csv_file': csv_upload(content)},
        )

        self.assertEqual(response.status_code, 200)
        result = response.context['result']
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['updated'], 1)

        club.refresh_from_db()
        old_president.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(club.name, 'Updated Club')
        self.assertEqual(club.teacher, 'Teacher Import (teacher-import)')
        self.assertEqual(club.president, 'Student Import (student-import)')
        self.assertEqual(old_president.role, 'student')
        self.assertEqual(old_president.club, club)
        self.assertEqual(self.student.role, 'president')
        self.assertEqual(self.student.club, club)
        self.assertEqual(club.current_members, 2)

    def test_import_skips_invalid_rows_and_reports_errors(self):
        self.client.force_login(self.admin)
        content = (
            'code,name,teacher_username,president_username,location,max_members\n'
            'C003,Valid Club,teacher-import,student-import,Room 3,10\n'
            ',Missing Code,,,Room 4,10\n'
            'C004,Bad Max,,,Room 5,0\n'
        )

        response = self.client.post(
            reverse('club_admin_import'),
            {'csv_file': csv_upload(content)},
        )

        self.assertEqual(response.status_code, 200)
        result = response.context['result']
        self.assertEqual(result['created'], 1)
        self.assertEqual(result['skipped'], 2)
        self.assertEqual(len(result['errors']), 2)
        self.assertTrue(Club.objects.filter(code='C003').exists())
        self.assertFalse(Club.objects.filter(code='C004').exists())
        self.assertContains(response, 'code 為必填欄位。')
        self.assertContains(response, 'max_members 必須是大於 0 的整數。')


class TeacherAdminManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='teacher-admin',
            password='password',
            role='admin',
        )
        self.teacher = User.objects.create_user(
            username='managed-teacher',
            password='old-password',
            first_name='Managed Teacher',
            email='managed.teacher@dcsh.tp.edu.tw',
            role='teacher',
            is_active=True,
        )
        self.club = Club.objects.create(
            code='T001',
            name='Teacher Club',
            teacher='Managed Teacher (managed-teacher)',
        )
        self.client.force_login(self.admin)

    def test_admin_can_access_teacher_management_and_account_navbar_link(self):
        response = self.client.get(reverse('teacher_admin_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '指導老師管理')
        self.assertContains(response, self.teacher.email)
        self.assertContains(response, self.club.name)

        home_response = self.client.get(reverse('home'))
        self.assertContains(home_response, reverse('account_admin_list'))
        self.assertContains(home_response, '帳號管理')
        self.assertNotContains(home_response, '指導老師管理')

    def test_student_president_and_teacher_cannot_access_teacher_management(self):
        roles = ['student', 'president', 'teacher']
        for role in roles:
            user = User.objects.create_user(
                username=f'{role}-no-teacher-admin',
                password='password',
                role=role,
            )
            self.client.force_login(user)

            response = self.client.get(reverse('teacher_admin_list'))

            self.assertEqual(response.status_code, 403)

    def test_create_teacher(self):
        response = self.client.post(
            reverse('teacher_admin_create'),
            {
                'username': 'new-teacher',
                'first_name': 'New Teacher',
                'email': 'new.teacher@dcsh.tp.edu.tw',
                'password': 'Valid-Teacher-937!',
                'password_confirm': 'Valid-Teacher-937!',
            },
        )

        self.assertRedirects(response, reverse('teacher_admin_list'))
        teacher = User.objects.get(email='new.teacher@dcsh.tp.edu.tw')
        self.assertEqual(teacher.role, 'teacher')
        self.assertTrue(teacher.is_active)
        self.assertEqual(teacher.first_name, 'New Teacher')
        self.assertTrue(teacher.check_password('Valid-Teacher-937!'))

    def test_edit_teacher_keeps_role_and_blank_password(self):
        response = self.client.post(
            reverse('teacher_admin_edit', args=[self.teacher.pk]),
            {
                'username': self.teacher.username,
                'first_name': 'Updated Teacher',
                'email': 'updated.teacher@dcsh.tp.edu.tw',
                'is_active': 'on',
                'password': '',
                'password_confirm': '',
            },
        )

        self.assertRedirects(response, reverse('teacher_admin_list'))
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.username, 'managed-teacher')
        self.assertEqual(self.teacher.first_name, 'Updated Teacher')
        self.assertEqual(self.teacher.email, 'updated.teacher@dcsh.tp.edu.tw')
        self.assertEqual(self.teacher.role, 'teacher')
        self.assertTrue(self.teacher.check_password('old-password'))

    def test_deactivate_teacher_clears_club_teacher(self):
        response = self.client.post(reverse('teacher_admin_deactivate', args=[self.teacher.pk]))

        self.assertRedirects(response, reverse('teacher_admin_list'))
        self.teacher.refresh_from_db()
        self.club.refresh_from_db()
        self.assertFalse(self.teacher.is_active)
        self.assertEqual(self.teacher.role, 'teacher')
        self.assertEqual(self.club.teacher, '')

    def test_reactivate_teacher(self):
        self.teacher.is_active = False
        self.teacher.save(update_fields=['is_active'])

        response = self.client.post(reverse('teacher_admin_reactivate', args=[self.teacher.pk]))

        self.assertRedirects(response, reverse('teacher_admin_list'))
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.is_active)
        self.assertEqual(self.teacher.role, 'teacher')

    def test_delete_teacher_without_history_deletes_and_clears_club_teacher(self):
        response = self.client.post(reverse('teacher_admin_delete', args=[self.teacher.pk]))

        self.assertRedirects(response, reverse('teacher_admin_list'))
        self.assertFalse(User.objects.filter(pk=self.teacher.pk).exists())
        self.club.refresh_from_db()
        self.assertEqual(self.club.teacher, '')
        self.assertTrue(Club.objects.filter(pk=self.club.pk).exists())

    def test_delete_teacher_with_history_deactivates_and_clears_club_teacher(self):
        student = User.objects.create_user(username='teacher-history-student', role='student')
        target_club = Club.objects.create(code='T002', name='Target Teacher Club')
        transfer_request = TransferRequest.objects.create(
            student=student,
            original_club=self.club,
            target_club=target_club,
        )
        ApprovalLog.objects.create(
            transfer_request=transfer_request,
            approver=self.teacher,
            approval_stage='orig_teacher_pending',
            result='approve',
        )

        response = self.client.post(reverse('teacher_admin_delete', args=[self.teacher.pk]))

        self.assertRedirects(response, reverse('teacher_admin_list'))
        self.teacher.refresh_from_db()
        self.club.refresh_from_db()
        self.assertFalse(self.teacher.is_active)
        self.assertEqual(self.teacher.role, 'teacher')
        self.assertEqual(self.club.teacher, '')
        self.assertTrue(TransferRequest.objects.filter(pk=transfer_request.pk).exists())


class AccountAdminListViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='account-admin',
            password='password',
            role='admin',
        )
        self.superuser = User.objects.create_superuser(
            username='account-superuser',
            password='password',
            email='superuser@example.com',
        )
        self.club = Club.objects.create(code='ACC', name='Account Club')
        self.student = User.objects.create_user(
            username='account-student',
            password='password',
            first_name='Student Name',
            email='s100@dcsh.tp.edu.tw',
            student_id='S100',
            class_name='101',
            seat_number=1,
            role='student',
            club=self.club,
        )
        self.president = User.objects.create_user(
            username='account-president',
            password='password',
            first_name='President Name',
            email='p100@dcsh.tp.edu.tw',
            student_id='P100',
            class_name='102',
            seat_number=2,
            role='president',
            club=self.club,
        )
        self.teacher = User.objects.create_user(
            username='account-teacher',
            password='password',
            first_name='Teacher Name',
            email='account.teacher@dcsh.tp.edu.tw',
            role='teacher',
        )
        self.hidden_admin = User.objects.create_user(
            username='hidden-admin',
            password='password',
            role='admin',
        )

    def test_admin_and_superuser_can_access_account_management(self):
        for user in [self.admin, self.superuser]:
            self.client.force_login(user)

            response = self.client.get(reverse('account_admin_list'))

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, '帳號管理')

    def test_non_admin_roles_cannot_access_account_management(self):
        for user in [self.student, self.president, self.teacher]:
            self.client.force_login(user)

            response = self.client.get(reverse('account_admin_list'))

            self.assertEqual(response.status_code, 403)

    def test_account_management_lists_students_presidents_and_teachers_only(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('account_admin_list'))

        self.assertEqual(response.status_code, 200)
        accounts = list(response.context['accounts'])
        self.assertIn(self.student, accounts)
        self.assertIn(self.president, accounts)
        self.assertIn(self.teacher, accounts)
        self.assertNotIn(self.admin, accounts)
        self.assertNotIn(self.hidden_admin, accounts)
        self.assertNotIn(self.superuser, accounts)

    def test_admin_accounts_are_protected_from_non_admin_delete_routes(self):
        self.client.force_login(self.admin)

        student_delete = self.client.post(
            reverse('student_admin_delete', args=[self.hidden_admin.pk]),
        )
        teacher_delete = self.client.post(
            reverse('teacher_admin_delete', args=[self.hidden_admin.pk]),
        )
        bulk_delete = self.client.post(
            reverse('account_admin_bulk_delete'),
            {'account_ids': [self.admin.pk, self.hidden_admin.pk, self.superuser.pk]},
        )

        self.assertEqual(student_delete.status_code, 404)
        self.assertEqual(teacher_delete.status_code, 404)
        self.assertRedirects(bulk_delete, reverse('account_admin_list'))
        self.assertEqual(
            User.objects.filter(
                pk__in=[self.admin.pk, self.hidden_admin.pk, self.superuser.pk],
            ).count(),
            3,
        )

    def test_account_management_role_filter(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('account_admin_list'), {'role': 'teacher'})

        accounts = list(response.context['accounts'])
        self.assertEqual(accounts, [self.teacher])
        self.assertContains(response, 'selected')

    def test_account_management_searches_supported_fields(self):
        self.client.force_login(self.admin)
        searches = [
            ('account-student', self.student),
            ('President Name', self.president),
            ('S100', self.student),
            ('account.teacher@dcsh.tp.edu.tw', self.teacher),
        ]

        for query, expected_account in searches:
            response = self.client.get(reverse('account_admin_list'), {'q': query})

            accounts = list(response.context['accounts'])
            self.assertIn(expected_account, accounts)

    def test_account_management_displays_requested_columns_and_teacher_blanks(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('account_admin_list'))

        self.assertContains(response, '姓名')
        self.assertContains(response, '身分')
        self.assertContains(response, 'Email')
        self.assertContains(response, '班級')
        self.assertContains(response, '座號')
        self.assertContains(response, '社團')
        self.assertContains(response, '狀態')
        self.assertContains(response, '操作')
        self.assertContains(response, '學生')
        self.assertContains(response, '社長')
        self.assertContains(response, '指導老師')
        self.assertContains(response, '啟用')
        self.assertContains(response, '—')

    def test_account_management_uses_existing_operation_urls_by_role(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('account_admin_list'))

        self.assertContains(response, reverse('student_admin_edit', args=[self.student.pk]))
        self.assertContains(response, reverse('student_admin_deactivate', args=[self.student.pk]))
        self.assertContains(response, reverse('student_admin_delete', args=[self.student.pk]))
        self.assertContains(response, reverse('teacher_admin_edit', args=[self.teacher.pk]))
        self.assertContains(response, reverse('teacher_admin_deactivate', args=[self.teacher.pk]))
        self.assertContains(response, reverse('teacher_admin_delete', args=[self.teacher.pk]))

    def test_account_management_has_bulk_controls_and_auto_role_filter(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('account_admin_list'))

        self.assertContains(response, 'account-checkbox')
        self.assertContains(response, '全選')
        self.assertContains(response, '取消全選')
        self.assertContains(response, '批次刪除')
        self.assertContains(response, '批次停用')
        self.assertContains(response, '批次重新啟用')
        self.assertContains(response, reverse('account_admin_bulk_delete_confirm'))
        self.assertContains(response, reverse('account_admin_bulk_deactivate'))
        self.assertContains(response, reverse('account_admin_bulk_reactivate'))
        self.assertContains(response, reverse('account_admin_create'))
        self.assertContains(response, reverse('account_admin_import'))
        self.assertNotContains(response, '新增學生')
        self.assertNotContains(response, '新增指導老師')
        self.assertNotContains(response, '>篩選<')
        self.assertContains(response, 'account-role-filter')
        self.assertContains(response, 'filterForm.submit()')

    def test_account_bulk_deactivate_only_affects_allowed_accounts_and_clears_assignments(self):
        self.club.president = 'President Name (account-president)'
        self.club.teacher = 'Teacher Name (account-teacher)'
        self.club.current_members = 2
        self.club.save(update_fields=['president', 'teacher', 'current_members'])
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('account_admin_bulk_deactivate'),
            {
                'account_ids': [
                    self.student.pk,
                    self.president.pk,
                    self.teacher.pk,
                    self.hidden_admin.pk,
                    self.superuser.pk,
                ],
            },
        )

        self.assertRedirects(response, reverse('account_admin_list'))
        self.student.refresh_from_db()
        self.president.refresh_from_db()
        self.teacher.refresh_from_db()
        self.hidden_admin.refresh_from_db()
        self.superuser.refresh_from_db()
        self.club.refresh_from_db()
        self.assertFalse(self.student.is_active)
        self.assertTrue(self.president.is_active)
        self.assertFalse(self.teacher.is_active)
        self.assertTrue(self.hidden_admin.is_active)
        self.assertTrue(self.superuser.is_active)
        self.assertEqual(self.club.president, 'President Name (account-president)')
        self.assertEqual(self.club.teacher, '')
        self.assertEqual(self.club.current_members, 1)

    def test_account_bulk_reactivate_only_affects_allowed_accounts(self):
        self.student.is_active = False
        self.student.save(update_fields=['is_active'])
        self.teacher.is_active = False
        self.teacher.save(update_fields=['is_active'])
        self.hidden_admin.is_active = False
        self.hidden_admin.save(update_fields=['is_active'])
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('account_admin_bulk_reactivate'),
            {
                'account_ids': [
                    self.student.pk,
                    self.teacher.pk,
                    self.hidden_admin.pk,
                    self.superuser.pk,
                ],
            },
        )

        self.assertRedirects(response, reverse('account_admin_list'))
        self.student.refresh_from_db()
        self.teacher.refresh_from_db()
        self.hidden_admin.refresh_from_db()
        self.superuser.refresh_from_db()
        self.assertTrue(self.student.is_active)
        self.assertTrue(self.teacher.is_active)
        self.assertFalse(self.hidden_admin.is_active)
        self.assertTrue(self.superuser.is_active)

    def test_account_bulk_delete_uses_safe_delete_for_students_and_teachers(self):
        student_without_history = User.objects.create_user(
            username='account-bulk-delete-student',
            password='password',
            role='student',
            student_id='BD001',
            club=self.club,
        )
        student_with_history = User.objects.create_user(
            username='account-bulk-history-student',
            password='password',
            role='student',
            student_id='BD002',
            club=self.club,
        )
        teacher_with_history = User.objects.create_user(
            username='account-bulk-history-teacher',
            password='password',
            role='teacher',
            first_name='Bulk Teacher',
        )
        self.club.teacher = 'Bulk Teacher (account-bulk-history-teacher)'
        self.club.save(update_fields=['teacher'])
        other_club = Club.objects.create(code='BDO', name='Bulk Delete Other')
        transfer_request = TransferRequest.objects.create(
            student=student_with_history,
            original_club=self.club,
            target_club=other_club,
            status='approved',
        )
        ApprovalLog.objects.create(
            transfer_request=transfer_request,
            approver=teacher_with_history,
            approval_stage='orig_teacher_pending',
            result='approve',
        )
        self.client.force_login(self.admin)

        confirm_response = self.client.post(
            reverse('account_admin_bulk_delete_confirm'),
            {
                'account_ids': [
                    student_without_history.pk,
                    student_with_history.pk,
                    teacher_with_history.pk,
                    self.hidden_admin.pk,
                ],
            },
        )

        self.assertEqual(confirm_response.status_code, 200)
        accounts = list(confirm_response.context['accounts'])
        self.assertIn(student_without_history, accounts)
        self.assertIn(student_with_history, accounts)
        self.assertIn(teacher_with_history, accounts)
        self.assertNotIn(self.hidden_admin, accounts)

        response = self.client.post(
            reverse('account_admin_bulk_delete'),
            {
                'account_ids': [
                    student_without_history.pk,
                    student_with_history.pk,
                    teacher_with_history.pk,
                    self.hidden_admin.pk,
                ],
            },
        )

        self.assertRedirects(response, reverse('account_admin_list'))
        self.assertFalse(User.objects.filter(pk=student_without_history.pk).exists())
        student_with_history.refresh_from_db()
        teacher_with_history.refresh_from_db()
        self.hidden_admin.refresh_from_db()
        self.club.refresh_from_db()
        self.assertFalse(student_with_history.is_active)
        self.assertFalse(teacher_with_history.is_active)
        self.assertTrue(self.hidden_admin.is_active)
        self.assertEqual(self.club.teacher, '')

    def test_account_create_generates_student_and_teacher_accounts(self):
        self.client.force_login(self.admin)

        student_response = self.client.post(
            reverse('account_admin_create'),
            {
                'role': 'student',
                'login_id': 's030112',
                'first_name': 'Generated Student',
                'email': 's030112@dcsh.tp.edu.tw',
                'class_name': '301',
                'seat_number': 12,
                'club': '',
                'password': 'Valid-Student-937!',
                'password_confirm': 'Valid-Student-937!',
            },
        )
        teacher_response = self.client.post(
            reverse('account_admin_create'),
            {
                'role': 'teacher',
                'login_id': 'generated-teacher',
                'first_name': 'Generated Teacher',
                'email': 'generated.teacher@dcsh.tp.edu.tw',
                'class_name': '',
                'seat_number': '',
                'club': '',
                'password': 'Valid-Teacher-482!',
                'password_confirm': 'Valid-Teacher-482!',
            },
        )

        self.assertRedirects(student_response, reverse('account_admin_list'))
        self.assertRedirects(teacher_response, reverse('account_admin_list'))
        student = User.objects.get(email='s030112@dcsh.tp.edu.tw')
        teacher = User.objects.get(email='generated.teacher@dcsh.tp.edu.tw')
        self.assertEqual(student.role, 'student')
        self.assertEqual(student.username, 's030112')
        self.assertEqual(student.student_id, 's030112')
        self.assertEqual(student.class_name, '301')
        self.assertEqual(student.seat_number, 12)
        self.assertIsNone(student.club)
        self.assertEqual(teacher.role, 'teacher')
        self.assertEqual(teacher.username, 'generated-teacher')
        self.assertEqual(teacher.student_id, '')
        self.assertTrue(student.check_password('Valid-Student-937!'))
        self.assertTrue(teacher.check_password('Valid-Teacher-482!'))

    def test_account_csv_import_creates_students_and_teachers(self):
        active_club = Club.objects.create(code='CSV01', name='CSV Active Club', is_active=True)
        inactive_club = Club.objects.create(code='CSV02', name='CSV Inactive Club', is_active=False)
        self.client.force_login(self.admin)
        content = (
            'role,login_id,name,email,class_name,seat_number,club_name,password\n'
            'student,s010101,王柏翰,s010101@example.invalid,101,1,CSV Active Club,Valid-Student-101!\n'
            'student,s010102,陳冠宇,s010102@example.invalid,101,2,,Valid-Student-102!\n'
            'teacher,teacher001,林建宏,teacher001@example.invalid,,,,Valid-Teacher-101!\n'
            'boss,bad-role,Bad Role,bad-role@example.invalid,,,,Valid-Invalid-101!\n'
            'student,bad-club,Bad Club,bad-club@example.invalid,403,5,CSV Inactive Club,Valid-Invalid-102!\n'
        )

        response = self.client.post(
            reverse('account_admin_import'),
            {
                'csv_file': uploaded_file(
                    'excel-utf8.csv',
                    content.encode('utf-8-sig'),
                    'text/csv',
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        result = response.context['result']
        self.assertEqual(result['created'], 3)
        self.assertEqual(result['updated'], 0)
        self.assertEqual(result['skipped'], 2)
        student = User.objects.get(username='s010101')
        unassigned = User.objects.get(username='s010102')
        teacher = User.objects.get(username='teacher001')
        self.assertEqual(student.role, 'student')
        self.assertEqual(student.first_name, '王柏翰')
        self.assertEqual(student.student_id, 's010101')
        self.assertEqual(student.class_name, '101')
        self.assertEqual(student.seat_number, 1)
        self.assertEqual(student.club, active_club)
        self.assertTrue(student.check_password('Valid-Student-101!'))
        active_club.refresh_from_db()
        self.assertEqual(active_club.current_members, 1)
        self.assertEqual(unassigned.role, 'student')
        self.assertIsNone(unassigned.club)
        self.assertTrue(unassigned.check_password('Valid-Student-102!'))
        self.assertEqual(teacher.role, 'teacher')
        self.assertEqual(teacher.first_name, '林建宏')
        self.assertEqual(teacher.student_id, '')
        self.assertEqual(teacher.class_name, '')
        self.assertIsNone(teacher.seat_number)
        self.assertIsNone(teacher.club)
        self.assertTrue(teacher.check_password('Valid-Teacher-101!'))
        self.assertFalse(User.objects.filter(username='bad-role').exists())
        self.assertFalse(User.objects.filter(username='bad-club').exists())
        self.assertContains(response, '匯入完成，部分資料未處理')
        self.assertContains(response, '已成功保留可處理的資料')
        self.assertContains(response, 'role 只接受 student 或 teacher')
        self.assertContains(response, '找不到啟用中的社團「CSV Inactive Club」。')

    def test_account_csv_import_rejects_xlsx_upload(self):
        self.client.force_login(self.admin)
        user_count = User.objects.count()

        response = self.client.post(
            reverse('account_admin_import'),
            {
                'csv_file': uploaded_file(
                    'accounts.xlsx',
                    b'not a csv file',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['result'])
        self.assertEqual(User.objects.count(), user_count)
        self.assertContains(response, '本系統不支援 .xlsx 檔案。請上傳 .csv 檔案。')

    def test_student_operations_from_account_management_return_to_account_list(self):
        self.client.force_login(self.admin)

        edit_response = self.client.post(
            f"{reverse('student_admin_edit', args=[self.student.pk])}?next=account_admin_list",
            {
                'username': self.student.username,
                'student_id': self.student.student_id,
                'class_name': self.student.class_name,
                'seat_number': self.student.seat_number,
                'first_name': 'Updated Student Name',
                'email': self.student.email,
                'role': 'student',
                'club': self.club.pk,
                'is_active': 'on',
                'password': '',
                'password_confirm': '',
                'next': 'account_admin_list',
            },
        )
        self.assertRedirects(edit_response, reverse('account_admin_list'))

        deactivate_response = self.client.post(
            reverse('student_admin_deactivate', args=[self.student.pk]),
            {'next': 'account_admin_list'},
        )
        self.assertRedirects(deactivate_response, reverse('account_admin_list'))

        reactivate_response = self.client.post(
            reverse('student_admin_reactivate', args=[self.student.pk]),
            {'next': 'account_admin_list'},
        )
        self.assertRedirects(reactivate_response, reverse('account_admin_list'))

        delete_target = User.objects.create_user(
            username='delete-from-account-student',
            password='password',
            role='student',
            student_id='DEL001',
            club=self.club,
        )
        delete_response = self.client.post(
            reverse('student_admin_delete', args=[delete_target.pk]),
            {'next': 'account_admin_list'},
        )
        self.assertRedirects(delete_response, reverse('account_admin_list'))

        create_response = self.client.post(
            f"{reverse('student_admin_create')}?next=account_admin_list",
            {
                'username': 'created-from-account-student',
                'student_id': 'CRE001',
                'class_name': '201',
                'seat_number': 8,
                'first_name': 'Created Student',
                'email': 's020108@dcsh.tp.edu.tw',
                'role': 'student',
                'club': '',
                'is_active': 'on',
                'password': 'Valid-Student-824!',
                'password_confirm': 'Valid-Student-824!',
                'next': 'account_admin_list',
            },
        )
        self.assertRedirects(create_response, reverse('account_admin_list'))

    def test_teacher_operations_from_account_management_return_to_account_list(self):
        self.client.force_login(self.admin)

        edit_response = self.client.post(
            f"{reverse('teacher_admin_edit', args=[self.teacher.pk])}?next=account_admin_list",
            {
                'username': self.teacher.username,
                'first_name': 'Updated Teacher Name',
                'email': self.teacher.email,
                'is_active': 'on',
                'password': '',
                'password_confirm': '',
                'next': 'account_admin_list',
            },
        )
        self.assertRedirects(edit_response, reverse('account_admin_list'))

        deactivate_response = self.client.post(
            reverse('teacher_admin_deactivate', args=[self.teacher.pk]),
            {'next': 'account_admin_list'},
        )
        self.assertRedirects(deactivate_response, reverse('account_admin_list'))

        reactivate_response = self.client.post(
            reverse('teacher_admin_reactivate', args=[self.teacher.pk]),
            {'next': 'account_admin_list'},
        )
        self.assertRedirects(reactivate_response, reverse('account_admin_list'))

        delete_target = User.objects.create_user(
            username='delete-from-account-teacher',
            password='password',
            role='teacher',
            first_name='Delete Teacher',
        )
        delete_response = self.client.post(
            reverse('teacher_admin_delete', args=[delete_target.pk]),
            {'next': 'account_admin_list'},
        )
        self.assertRedirects(delete_response, reverse('account_admin_list'))

        create_response = self.client.post(
            f"{reverse('teacher_admin_create')}?next=account_admin_list",
            {
                'username': 'created-from-account-teacher',
                'first_name': 'Created Teacher',
                'email': 'created.teacher@dcsh.tp.edu.tw',
                'is_active': 'on',
                'password': 'Valid-Teacher-824!',
                'password_confirm': 'Valid-Teacher-824!',
                'next': 'account_admin_list',
            },
        )
        self.assertRedirects(create_response, reverse('account_admin_list'))

    def test_navbar_links_to_account_management_only(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('home'))

        self.assertContains(response, reverse('account_admin_list'))
        self.assertContains(response, '帳號管理')
        self.assertNotContains(response, '學生管理')
        self.assertNotContains(response, '指導老師管理')


class AdminProfileTests(TestCase):
    def test_admin_profile_hides_student_fields_and_can_edit_self(self):
        admin = User.objects.create_user(
            username='profile-admin',
            password='old-password',
            role='admin',
            first_name='Profile Admin',
            email='old@example.com',
            student_id='ADMIN001',
            class_name='999',
            seat_number=1,
        )
        self.client.force_login(admin)

        profile_response = self.client.get(reverse('profile'))

        self.assertContains(profile_response, '編輯個人資料')
        self.assertNotContains(profile_response, '學號')
        self.assertNotContains(profile_response, '所屬社團')

        edit_response = self.client.post(
            reverse('admin_profile_edit'),
            {
                'username': 'updated-profile-admin',
                'first_name': 'Updated Admin',
                'email': 'updated@example.com',
                'password': '',
            },
        )

        self.assertRedirects(edit_response, reverse('profile'))
        admin.refresh_from_db()
        self.assertEqual(admin.username, 'updated-profile-admin')
        self.assertEqual(admin.first_name, 'Updated Admin')
        self.assertEqual(admin.email, 'updated@example.com')
        self.assertTrue(admin.check_password('old-password'))

        password_response = self.client.post(
            reverse('admin_profile_edit'),
            {
                'username': admin.username,
                'first_name': admin.first_name,
                'email': admin.email,
                'password': 'new-password',
                'password_confirm': 'new-password',
            },
        )

        self.assertRedirects(password_response, reverse('profile'))
        admin.refresh_from_db()
        self.assertTrue(admin.check_password('new-password'))

    def test_non_admin_profile_is_unchanged_and_cannot_edit_admin_profile(self):
        student = User.objects.create_user(
            username='profile-student',
            password='password',
            role='student',
            student_id='ST001',
        )
        self.client.force_login(student)

        profile_response = self.client.get(reverse('profile'))
        edit_response = self.client.get(reverse('admin_profile_edit'))

        self.assertContains(profile_response, '學號')
        self.assertContains(profile_response, '所屬社團')
        self.assertNotContains(profile_response, '編輯個人資料')
        self.assertEqual(edit_response.status_code, 403)


class UnassignedStudentAssignClubViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='assign-admin',
            password='password',
            role='admin',
        )
        self.student = User.objects.create_user(
            username='unassigned-student',
            role='student',
            is_active=True,
        )
        self.active_club = Club.objects.create(code='A001', name='Active Club')
        self.inactive_club = Club.objects.create(
            code='I001',
            name='Inactive Club',
            is_active=False,
        )
        self.client.force_login(self.admin)

    def test_unassigned_page_lists_active_clubs_and_assigns_student(self):
        response = self.client.get(reverse('unassigned_account_list'))

        self.assertContains(response, reverse('unassigned_student_assign_club', args=[self.student.pk]))
        self.assertContains(response, self.active_club.name)
        self.assertNotContains(response, self.inactive_club.name)
        self.assertContains(response, '<th>姓名</th>', html=True)
        self.assertContains(response, '<th>身分</th>', html=True)
        self.assertContains(response, '<th>Email</th>', html=True)
        self.assertContains(response, '<th>班級</th>', html=True)
        self.assertContains(response, '<th>座號</th>', html=True)
        self.assertNotContains(response, '<th>社團</th>', html=True)

        response = self.client.post(
            reverse('unassigned_student_assign_club', args=[self.student.pk]),
            {'club_id': self.active_club.pk},
        )

        self.assertRedirects(response, reverse('unassigned_account_list'))
        self.student.refresh_from_db()
        self.active_club.refresh_from_db()
        self.assertEqual(self.student.role, 'student')
        self.assertEqual(self.student.club, self.active_club)
        self.assertEqual(self.active_club.current_members, 1)

    def test_inactive_club_cannot_be_assigned(self):
        response = self.client.post(
            reverse('unassigned_student_assign_club', args=[self.student.pk]),
            {'club_id': self.inactive_club.pk},
        )

        self.assertEqual(response.status_code, 404)
        self.student.refresh_from_db()
        self.assertIsNone(self.student.club)

    def test_non_admin_cannot_assign_student(self):
        other_student = User.objects.create_user(username='other-student', role='student')
        self.client.force_login(other_student)

        response = self.client.post(
            reverse('unassigned_student_assign_club', args=[self.student.pk]),
            {'club_id': self.active_club.pk},
        )

        self.assertEqual(response.status_code, 403)
        self.student.refresh_from_db()
        self.assertIsNone(self.student.club)


class ClubAdminFormWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='club-form-admin',
            password='password',
            role='admin',
        )
        self.student = User.objects.create_user(
            username='available-student',
            first_name='Available Student',
            role='student',
            is_active=True,
        )
        self.teacher = User.objects.create_user(
            username='available-teacher',
            first_name='Available Teacher',
            role='teacher',
            is_active=True,
        )
        self.client.force_login(self.admin)

    def club_form_data(self, **overrides):
        data = {
            'code': 'NEW01',
            'name': 'New Club',
            'teacher': self.teacher.pk,
            'president': self.student.pk,
            'location': '',
            'description': '',
            'max_members': 30,
        }
        data.update(overrides)
        return data

    def test_create_club_uses_unassigned_account_dropdowns(self):
        assigned_club = Club.objects.create(
            code='USED',
            name='Used Club',
            teacher='Used Teacher (used-teacher)',
        )
        assigned_student = User.objects.create_user(
            username='assigned-student',
            role='student',
            club=assigned_club,
        )
        used_teacher = User.objects.create_user(
            username='used-teacher',
            first_name='Used Teacher',
            role='teacher',
        )

        form = ClubAdminForm()

        self.assertIn(self.student, form.fields['president'].queryset)
        self.assertNotIn(assigned_student, form.fields['president'].queryset)
        self.assertIn(self.teacher, form.fields['teacher'].queryset)
        self.assertNotIn(used_teacher, form.fields['teacher'].queryset)

        response = self.client.post(reverse('club_admin_create'), self.club_form_data())

        self.assertRedirects(response, reverse('club_admin_list'))
        club = Club.objects.get(code='NEW01')
        self.student.refresh_from_db()
        self.assertEqual(club.president, 'Available Student (available-student)')
        self.assertEqual(club.teacher, 'Available Teacher (available-teacher)')
        self.assertEqual(self.student.role, 'president')
        self.assertEqual(self.student.club, club)
        self.assertEqual(club.current_members, 1)

    def test_update_club_changes_president_and_keeps_old_president_in_club(self):
        club = Club.objects.create(
            code='EDIT',
            name='Edit Club',
            teacher='Available Teacher (available-teacher)',
            president='Old President (old-president)',
        )
        old_president = User.objects.create_user(
            username='old-president',
            first_name='Old President',
            role='president',
            club=club,
        )
        new_president = User.objects.create_user(
            username='new-president',
            first_name='New President',
            role='student',
        )

        response = self.client.post(
            reverse('club_admin_edit', args=[club.pk]),
            self.club_form_data(
                code=club.code,
                name=club.name,
                president=new_president.pk,
            ),
        )

        self.assertRedirects(response, reverse('club_admin_list'))
        club.refresh_from_db()
        old_president.refresh_from_db()
        new_president.refresh_from_db()
        self.assertEqual(club.president, 'New President (new-president)')
        self.assertEqual(old_president.role, 'student')
        self.assertEqual(old_president.club, club)
        self.assertEqual(new_president.role, 'president')
        self.assertEqual(new_president.club, club)
        self.assertEqual(club.current_members, 2)


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
        self.president = User.objects.create_user(
            username='bulk-president',
            role='president',
            club=self.club,
        )
        self.club.president = 'Bulk President (bulk-president)'
        self.club.save(update_fields=['president'])
        self.teacher = User.objects.create_user(
            username='teacher',
            role='teacher',
            club=self.club,
        )
        self.client.force_login(self.admin)

    def test_student_admin_list_president_has_bulk_checkbox(self):
        response = self.client.get(reverse('student_admin_list'), {'q': self.president.username})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{self.president.pk}"')
        self.assertContains(response, 'student-checkbox')

    def test_bulk_deactivate_and_reactivate_students_and_presidents_only(self):
        self.club.current_members = 3
        self.club.save(update_fields=['current_members'])

        response = self.client.post(
            reverse('student_admin_bulk_deactivate'),
            {
                'student_ids': [
                    self.student_one.pk,
                    self.student_two.pk,
                    self.president.pk,
                    self.teacher.pk,
                    self.admin.pk,
                ],
            },
        )

        self.assertRedirects(response, reverse('student_admin_list'))
        self.student_one.refresh_from_db()
        self.student_two.refresh_from_db()
        self.president.refresh_from_db()
        self.teacher.refresh_from_db()
        self.admin.refresh_from_db()
        self.club.refresh_from_db()
        self.assertFalse(self.student_one.is_active)
        self.assertFalse(self.student_two.is_active)
        self.assertTrue(self.president.is_active)
        self.assertTrue(self.teacher.is_active)
        self.assertTrue(self.admin.is_active)
        self.assertEqual(self.club.president, 'Bulk President (bulk-president)')
        self.assertEqual(self.club.current_members, 1)

        response = self.client.post(
            reverse('student_admin_bulk_reactivate'),
            {
                'student_ids': [
                    self.student_one.pk,
                    self.student_two.pk,
                    self.president.pk,
                    self.teacher.pk,
                    self.admin.pk,
                ],
            },
        )

        self.assertRedirects(response, reverse('student_admin_list'))
        self.student_one.refresh_from_db()
        self.student_two.refresh_from_db()
        self.president.refresh_from_db()
        self.teacher.refresh_from_db()
        self.admin.refresh_from_db()
        self.club.refresh_from_db()
        self.assertTrue(self.student_one.is_active)
        self.assertTrue(self.student_two.is_active)
        self.assertTrue(self.president.is_active)
        self.assertTrue(self.teacher.is_active)
        self.assertTrue(self.admin.is_active)
        self.assertEqual(self.club.current_members, 3)

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
            status='approved',
        )
        ApprovalLog.objects.create(
            transfer_request=transfer_request,
            approver=self.student_one,
            approval_stage='orig_teacher_pending',
            result='approve',
        )
        self.club.current_members = 4
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
        self.assertEqual(self.club.current_members, 1)

    def test_bulk_delete_requires_replacement_for_active_president_without_history(self):
        self.club.current_members = 3
        self.club.save(update_fields=['current_members'])

        response = self.client.post(
            reverse('student_admin_bulk_delete'),
            {'student_ids': [self.president.pk]},
        )

        self.assertRedirects(response, reverse('student_admin_list'))
        self.president.refresh_from_db()
        self.club.refresh_from_db()
        self.assertTrue(self.president.is_active)
        self.assertEqual(self.president.role, 'president')
        self.assertEqual(self.president.club, self.club)
        self.assertNotEqual(self.club.president, '')
        self.assertEqual(self.club.current_members, 3)

    def test_bulk_delete_requires_replacement_for_active_president_with_history(self):
        transfer_request = TransferRequest.objects.create(
            student=self.president,
            original_club=self.club,
            target_club=self.other_club,
        )
        ApprovalLog.objects.create(
            transfer_request=transfer_request,
            approver=self.admin,
            approval_stage='admin_pending',
            result='approve',
        )
        self.club.current_members = 3
        self.club.save(update_fields=['current_members'])

        response = self.client.post(
            reverse('student_admin_bulk_delete'),
            {'student_ids': [self.president.pk]},
        )

        self.assertRedirects(response, reverse('student_admin_list'))
        self.president.refresh_from_db()
        self.club.refresh_from_db()
        self.assertTrue(self.president.is_active)
        self.assertEqual(self.president.role, 'president')
        self.assertEqual(self.president.club, self.club)
        self.assertNotEqual(self.club.president, '')
        self.assertEqual(self.club.current_members, 3)

    def test_bulk_delete_confirm_lists_students_and_presidents_only(self):
        response = self.client.post(
            reverse('student_admin_bulk_delete_confirm'),
            {'student_ids': [self.student_one.pk, self.president.pk, self.teacher.pk, self.admin.pk]},
        )

        self.assertEqual(response.status_code, 200)
        students = list(response.context['students'])
        self.assertEqual(students, [self.president, self.student_one])
        self.assertContains(response, self.student_one.username)
        self.assertContains(response, self.president.username)
        self.assertNotIn(self.teacher, students)
        self.assertNotIn(self.admin, students)

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
        self.assertContains(response, '編輯')
        self.assertContains(response, '停用')
        self.assertContains(response, '刪除')
        self.assertNotContains(response, '降級為一般學生')

    def test_editing_president_keeps_president_role_and_club_president(self):
        response = self.client.post(
            reverse('student_admin_edit', args=[self.president.pk]),
            {
                'username': self.president.username,
                'student_id': self.president.student_id,
                'class_name': '',
                'seat_number': '',
                'first_name': self.president.first_name,
                'email': 'p001@dcsh.tp.edu.tw',
                'role': 'president',
                'club': self.club.pk,
                'is_active': 'on',
                'password': '',
                'password_confirm': '',
            },
        )

        self.assertRedirects(response, reverse('student_admin_list'))
        self.president.refresh_from_db()
        self.club.refresh_from_db()
        self.assertEqual(self.president.role, 'president')
        self.assertEqual(self.president.club, self.club)
        self.assertEqual(self.club.president, 'President User (p001)')
        self.assertEqual(self.club.current_members, 1)

    def test_deactivating_president_requires_replacement(self):
        response = self.client.post(reverse('student_admin_deactivate', args=[self.president.pk]))

        self.assertRedirects(response, reverse('student_admin_list'))
        self.president.refresh_from_db()
        self.club.refresh_from_db()
        self.assertTrue(self.president.is_active)
        self.assertEqual(self.president.role, 'president')
        self.assertEqual(self.president.club, self.club)
        self.assertEqual(self.club.president, 'President User (president-user)')
        self.assertEqual(self.club.current_members, 1)

    def test_deleting_active_president_requires_replacement(self):
        response = self.client.post(reverse('student_admin_delete', args=[self.president.pk]))

        self.assertRedirects(response, reverse('student_admin_list'))
        self.president.refresh_from_db()
        self.club.refresh_from_db()
        self.assertTrue(self.president.is_active)
        self.assertEqual(self.president.role, 'president')
        self.assertEqual(self.president.club, self.club)
        self.assertEqual(self.club.president, 'President User (president-user)')
        self.assertEqual(self.club.current_members, 1)

    def test_deleting_active_president_with_history_requires_replacement(self):
        other_club = Club.objects.create(code='P002', name='Other President Club')
        transfer_request = TransferRequest.objects.create(
            student=self.president,
            original_club=self.club,
            target_club=other_club,
        )
        ApprovalLog.objects.create(
            transfer_request=transfer_request,
            approver=self.admin,
            approval_stage='admin_pending',
            result='approve',
        )

        response = self.client.post(reverse('student_admin_delete', args=[self.president.pk]))

        self.assertRedirects(response, reverse('student_admin_list'))
        self.president.refresh_from_db()
        self.club.refresh_from_db()
        self.assertTrue(self.president.is_active)
        self.assertEqual(self.president.role, 'president')
        self.assertEqual(self.president.club, self.club)
        self.assertEqual(self.club.president, 'President User (president-user)')
        self.assertEqual(self.club.current_members, 1)

    def test_president_can_be_deleted_after_replacement(self):
        replacement = User.objects.create_user(
            username='replacement-president',
            role='student',
            club=self.club,
        )
        self.club.current_members = 2
        self.club.save(update_fields=['current_members'])

        replace_response = self.client.post(
            reverse(
                'club_admin_replace_president',
                args=[self.club.pk, self.president.pk],
            ),
            {'new_president_id': replacement.pk},
        )
        self.assertRedirects(
            replace_response,
            reverse('club_admin_edit', args=[self.club.pk]),
        )

        delete_response = self.client.post(
            reverse('student_admin_delete', args=[self.president.pk]),
        )

        self.assertRedirects(delete_response, reverse('student_admin_list'))
        self.assertFalse(User.objects.filter(pk=self.president.pk).exists())
        replacement.refresh_from_db()
        self.club.refresh_from_db()
        self.assertEqual(replacement.role, 'president')
        self.assertEqual(replacement.club, self.club)
        self.assertIn(f'({replacement.username})', self.club.president)
        self.assertEqual(self.club.current_members, 1)


class PasswordAccountLifecycleTests(TestCase):
    password = 'Valid-Account-937!'

    def test_all_roles_can_use_normal_password_authentication(self):
        for role in ['admin', 'student', 'teacher', 'president']:
            login_id = f'{role}-login'
            user = User.objects.create_user(
                username=login_id,
                student_id=login_id if role in ['student', 'president'] else '',
                password=self.password,
                role=role,
            )
            with self.subTest(role=role):
                self.assertEqual(
                    authenticate(username=login_id, password=self.password),
                    user,
                )

    def test_wrong_password_and_inactive_user_are_rejected(self):
        user = User.objects.create_user(
            username='inactive-login',
            student_id='inactive-login',
            password=self.password,
            role='student',
            is_active=False,
        )
        self.assertIsNone(authenticate(username=user.username, password='wrong-password'))
        self.assertIsNone(authenticate(username=user.username, password=self.password))

    def test_admin_can_create_student_and_teacher_with_hashed_passwords(self):
        admin = User.objects.create_user(
            username='create-admin', password=self.password, role='admin'
        )
        self.client.force_login(admin)
        student_response = self.client.post(reverse('account_admin_create'), {
            'role': 'student',
            'login_id': ' S000101 ',
            'first_name': 'Synthetic Student',
            'email': ' STUDENT@EXAMPLE.INVALID ',
            'class_name': '101',
            'seat_number': '1',
            'club': '',
            'password': self.password,
            'password_confirm': self.password,
        })
        teacher_response = self.client.post(reverse('account_admin_create'), {
            'role': 'teacher',
            'login_id': ' Teacher.One ',
            'first_name': 'Synthetic Teacher',
            'email': '',
            'class_name': '',
            'seat_number': '',
            'club': '',
            'password': self.password,
            'password_confirm': self.password,
        })

        self.assertRedirects(student_response, reverse('account_admin_list'))
        self.assertRedirects(teacher_response, reverse('account_admin_list'))
        student = User.objects.get(username='s000101')
        teacher = User.objects.get(username='teacher.one')
        self.assertEqual(student.student_id, student.username)
        self.assertEqual(student.email, 'student@example.invalid')
        self.assertEqual(student.role, 'student')
        self.assertEqual(teacher.role, 'teacher')
        self.assertNotEqual(student.password, self.password)
        self.assertTrue(student.check_password(self.password))
        self.assertTrue(teacher.check_password(self.password))

    def test_weak_and_mismatched_passwords_are_rejected(self):
        admin = User.objects.create_user(
            username='password-admin', password=self.password, role='admin'
        )
        self.client.force_login(admin)
        weak = self.client.post(reverse('account_admin_create'), {
            'role': 'teacher', 'login_id': 'weak-teacher', 'first_name': 'Weak',
            'email': '', 'class_name': '', 'seat_number': '', 'club': '',
            'password': '123', 'password_confirm': '123',
        })
        mismatch = self.client.post(reverse('account_admin_create'), {
            'role': 'student', 'login_id': 'mismatch-student', 'first_name': 'Mismatch',
            'email': '', 'class_name': '', 'seat_number': '', 'club': '',
            'password': self.password, 'password_confirm': 'Different-Password-482!',
        })
        self.assertEqual(weak.status_code, 200)
        self.assertEqual(mismatch.status_code, 200)
        self.assertFalse(User.objects.filter(username__in=['weak-teacher', 'mismatch-student']).exists())

    def test_edit_with_blank_password_preserves_hash(self):
        admin = User.objects.create_user(
            username='edit-admin', password=self.password, role='admin'
        )
        student = User.objects.create_user(
            username='s000102', student_id='s000102', password=self.password,
            role='student', first_name='Before',
        )
        original_hash = student.password
        self.client.force_login(admin)
        response = self.client.post(reverse('student_admin_edit', args=[student.pk]), {
            'student_id': student.student_id,
            'class_name': '', 'seat_number': '', 'first_name': 'After',
            'email': '', 'role': 'student', 'club': '', 'is_active': 'on',
            'password': '', 'password_confirm': '',
        })
        self.assertRedirects(response, reverse('student_admin_list'))
        student.refresh_from_db()
        self.assertEqual(student.password, original_hash)
        self.assertEqual(student.username, student.student_id)

    def test_csv_creates_and_updates_accounts_without_echoing_password(self):
        admin = User.objects.create_user(
            username='csv-admin', password=self.password, role='admin'
        )
        self.client.force_login(admin)
        create_csv = (
            'role,login_id,name,email,class_name,seat_number,club_name,password\n'
            f'student,s000103,CSV Student,student103@example.invalid,101,3,,{self.password}\n'
            f'teacher,teacher.csv,CSV Teacher,,,,,{self.password}\n'
        )
        response = self.client.post(
            reverse('account_admin_import'), {'csv_file': csv_upload(create_csv)}
        )
        self.assertEqual(response.context['result']['created'], 2)
        self.assertNotContains(response, self.password)
        student = User.objects.get(username='s000103')
        original_hash = student.password

        update_csv = (
            'role,login_id,name,email,class_name,seat_number,club_name,password\n'
            'student,s000103,Updated Student,updated103@example.invalid,102,4,,\n'
        )
        update_response = self.client.post(
            reverse('account_admin_import'), {'csv_file': csv_upload(update_csv)}
        )
        self.assertEqual(update_response.context['result']['updated'], 1)
        student.refresh_from_db()
        self.assertEqual(student.first_name, 'Updated Student')
        self.assertEqual(student.password, original_hash)
        self.assertEqual(student.username, student.student_id)

    def test_csv_rejects_duplicates_invalid_role_and_president(self):
        admin = User.objects.create_user(
            username='csv-rejection-admin', password=self.password, role='admin'
        )
        self.client.force_login(admin)
        User.objects.create_user(
            username='existing-login', password=self.password, role='teacher',
            email='duplicate@example.invalid',
        )
        content = (
            'role,login_id,name,email,class_name,seat_number,club_name,password\n'
            f'student,new-login,Duplicate Email,DUPLICATE@EXAMPLE.INVALID,101,1,,{self.password}\n'
            f'president,president-login,President,,101,2,,{self.password}\n'
            f'boss,boss-login,Boss,,,,,{self.password}\n'
            f'student,existing-login,Role Conflict,,101,3,,{self.password}\n'
        )
        response = self.client.post(
            reverse('account_admin_import'), {'csv_file': csv_upload(content)}
        )
        result = response.context['result']
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['skipped'], 4)
        self.assertFalse(User.objects.filter(username='president-login').exists())
        self.assertFalse(User.objects.filter(username='boss-login').exists())

    def test_duplicate_student_id_and_nonempty_email_are_rejected_case_insensitively(self):
        User.objects.create_user(
            username='s000104', student_id='s000104', password=self.password,
            role='student', email='unique@example.invalid',
        )
        admin = User.objects.create_user(
            username='duplicate-admin', password=self.password, role='admin'
        )
        self.client.force_login(admin)
        duplicate_student = self.client.post(reverse('account_admin_create'), {
            'role': 'student', 'login_id': 'S000104', 'first_name': 'Duplicate',
            'email': '', 'class_name': '', 'seat_number': '', 'club': '',
            'password': self.password, 'password_confirm': self.password,
        })
        duplicate_email = self.client.post(reverse('account_admin_create'), {
            'role': 'teacher', 'login_id': 'different-login', 'first_name': 'Duplicate',
            'email': 'UNIQUE@EXAMPLE.INVALID', 'class_name': '', 'seat_number': '', 'club': '',
            'password': self.password, 'password_confirm': self.password,
        })
        self.assertEqual(duplicate_student.status_code, 200)
        self.assertEqual(duplicate_email.status_code, 200)
        self.assertEqual(User.objects.filter(email__iexact='unique@example.invalid').count(), 1)

    def test_president_promotion_preserves_student_identity_and_password(self):
        admin = User.objects.create_user(
            username='promotion-admin', password=self.password, role='admin'
        )
        club = Club.objects.create(code='AUTH', name='Authentication Club')
        student = User.objects.create_user(
            username='s000105', student_id='s000105', password=self.password,
            role='student', club=club,
        )
        identity = (student.pk, student.username, student.student_id, student.password)
        self.client.force_login(admin)
        response = self.client.post(
            reverse('account_admin_promote_president', args=[student.pk])
        )
        self.assertRedirects(response, reverse('account_admin_list'))
        student.refresh_from_db()
        self.assertEqual(
            (student.pk, student.username, student.student_id, student.password),
            identity,
        )
        self.assertEqual(student.role, 'president')
        self.assertEqual(
            authenticate(username=student.username, password=self.password),
            student,
        )

    def test_google_routes_are_not_available(self):
        self.assertEqual(self.client.get('/accounts/google/login/').status_code, 404)
        self.assertEqual(self.client.get('/accounts/google/login/callback/').status_code, 404)
