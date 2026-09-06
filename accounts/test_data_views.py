from django.test import TestCase
from django.urls import reverse

from .models import User


class AdvancedDataViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='table-admin',
            password='test-password',
            role='admin',
        )
        cls.teacher = User.objects.create_user(
            username='table-teacher',
            role='teacher',
            email='teacher@example.com',
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_account_list_uses_dense_table_and_selection_contract(self):
        response = self.client.get(reverse('account_admin_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="data-view"')
        self.assertContains(response, 'data-table--dense')
        self.assertContains(response, 'data-selection-checkbox=".account-checkbox"')
        self.assertContains(response, 'data-selected-count')

    def test_teacher_list_uses_mobile_card_table_strategy(self):
        response = self.client.get(reverse('teacher_admin_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-table--cards')
        self.assertContains(response, 'data-label="Email"')
        self.assertContains(response, 'class="data-row-actions"')

    def test_unassigned_list_exposes_bulk_toolbar_and_empty_state(self):
        response = self.client.get(
            reverse('unassigned_account_list'),
            {'q': 'no-matching-unassigned-account'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="bulk-action-bar"')
        self.assertContains(response, 'data-select-all')
        self.assertContains(response, '沒有未分配帳號')

    def test_club_search_uses_shared_toolbar_and_contextual_empty_state(self):
        response = self.client.get(reverse('club_list'), {'q': '不存在的社團'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="data-toolbar"')
        self.assertContains(response, '找不到符合的社團')
        self.assertContains(response, 'value="不存在的社團"')
