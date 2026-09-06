from django.test import TestCase
from django.urls import reverse

from .models import User


class WorkflowFormUxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='workflow-admin',
            password='test-password',
            role='admin',
        )
        cls.student = User.objects.create_user(
            username='workflow-student',
            password='test-password',
            role='student',
            student_id='WF001',
            first_name='流程學生',
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_account_create_uses_shared_sections_and_explicit_action(self):
        response = self.client.get(reverse('account_admin_create'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="form-shell"')
        self.assertContains(response, '身分與基本資料')
        self.assertContains(response, '初始密碼')
        self.assertContains(response, '建立帳號')
        self.assertContains(response, 'data-workflow-form')

    def test_invalid_account_form_preserves_values_and_links_field_error(self):
        response = self.client.post(
            reverse('account_admin_create'),
            {
                'role': 'student',
                'login_id': 'WF002',
                'first_name': '保留姓名',
                'email': 'kept@example.com',
                'password': 'one-password',
                'password_confirm': 'different-password',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="kept@example.com"')
        self.assertContains(response, '兩次輸入的密碼不一致')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, '請修正以下內容後再繼續')

    def test_transfer_window_form_explains_dates_and_unavailable_archive(self):
        response = self.client.get(reverse('transfer_window_settings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '申請開放日期')
        self.assertContains(response, '申請截止日期')
        self.assertContains(response, '學生無法建立轉社申請')

    def test_student_delete_confirmation_explains_possible_outcomes(self):
        response = self.client.get(
            reverse('student_admin_delete', args=[self.student.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="danger-zone"')
        self.assertContains(response, '系統會改為停用以保留歷史')
        self.assertContains(response, '刪除或停用此學生帳號')
