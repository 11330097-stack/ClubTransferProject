from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

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
            'C002,Updated Club,,student-import,Room 2,20\n'
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
        self.assertEqual(club.teacher, '')
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
            'C003,Valid Club,,,Room 3,10\n'
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
        self.assertContains(response, 'code is required.')
        self.assertContains(response, 'max_members must be a positive integer.')


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
            email='teacher@example.com',
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
        self.assertContains(response, self.teacher.username)
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
                'email': 'new@example.com',
                'password': 'new-password',
            },
        )

        self.assertRedirects(response, reverse('teacher_admin_list'))
        teacher = User.objects.get(username='new-teacher')
        self.assertEqual(teacher.role, 'teacher')
        self.assertTrue(teacher.is_active)
        self.assertEqual(teacher.first_name, 'New Teacher')
        self.assertEqual(teacher.email, 'new@example.com')
        self.assertTrue(teacher.check_password('new-password'))

    def test_edit_teacher_keeps_role_and_blank_password(self):
        old_password = self.teacher.password

        response = self.client.post(
            reverse('teacher_admin_edit', args=[self.teacher.pk]),
            {
                'username': 'updated-teacher',
                'first_name': 'Updated Teacher',
                'email': 'updated@example.com',
                'is_active': 'on',
                'password': '',
            },
        )

        self.assertRedirects(response, reverse('teacher_admin_list'))
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.username, 'updated-teacher')
        self.assertEqual(self.teacher.first_name, 'Updated Teacher')
        self.assertEqual(self.teacher.email, 'updated@example.com')
        self.assertEqual(self.teacher.role, 'teacher')
        self.assertEqual(self.teacher.password, old_password)

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
            email='student@example.com',
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
            email='president@example.com',
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
            email='teacher@example.com',
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
            ('teacher@example.com', self.teacher),
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
                'email': 'created-student@example.com',
                'role': 'student',
                'club': '',
                'is_active': 'on',
                'password': 'password',
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
                'email': 'created-teacher@example.com',
                'is_active': 'on',
                'password': 'password',
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
        self.assertFalse(self.president.is_active)
        self.assertTrue(self.teacher.is_active)
        self.assertTrue(self.admin.is_active)
        self.assertEqual(self.club.president, '')
        self.assertEqual(self.club.current_members, 0)

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

    def test_bulk_delete_deletes_president_without_history_and_clears_club_president(self):
        self.club.current_members = 3
        self.club.save(update_fields=['current_members'])

        response = self.client.post(
            reverse('student_admin_bulk_delete'),
            {'student_ids': [self.president.pk]},
        )

        self.assertRedirects(response, reverse('student_admin_list'))
        self.assertFalse(User.objects.filter(pk=self.president.pk).exists())
        self.club.refresh_from_db()
        self.assertEqual(self.club.president, '')
        self.assertEqual(self.club.current_members, 2)

    def test_bulk_delete_deactivates_president_with_history_and_clears_club_president(self):
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
        self.assertFalse(self.president.is_active)
        self.assertEqual(self.president.role, 'president')
        self.assertEqual(self.club.president, '')
        self.assertEqual(self.club.current_members, 2)

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
                'email': '',
                'role': 'president',
                'club': self.club.pk,
                'is_active': 'on',
                'password': '',
            },
        )

        self.assertRedirects(response, reverse('student_admin_list'))
        self.president.refresh_from_db()
        self.club.refresh_from_db()
        self.assertEqual(self.president.role, 'president')
        self.assertEqual(self.club.president, 'President User (president-user)')
        self.assertEqual(self.club.current_members, 1)

    def test_deactivating_president_clears_club_president(self):
        response = self.client.post(reverse('student_admin_deactivate', args=[self.president.pk]))

        self.assertRedirects(response, reverse('student_admin_list'))
        self.president.refresh_from_db()
        self.club.refresh_from_db()
        self.assertFalse(self.president.is_active)
        self.assertEqual(self.president.role, 'president')
        self.assertEqual(self.club.president, '')
        self.assertEqual(self.club.current_members, 0)

    def test_deleting_president_without_history_deletes_and_clears_club_president(self):
        response = self.client.post(reverse('student_admin_delete', args=[self.president.pk]))

        self.assertRedirects(response, reverse('student_admin_list'))
        self.assertFalse(User.objects.filter(pk=self.president.pk).exists())
        self.club.refresh_from_db()
        self.assertEqual(self.club.president, '')
        self.assertEqual(self.club.current_members, 0)

    def test_deleting_president_with_history_deactivates_and_clears_club_president(self):
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
        self.assertFalse(self.president.is_active)
        self.assertEqual(self.president.role, 'president')
        self.assertEqual(self.club.president, '')
        self.assertEqual(self.club.current_members, 0)
