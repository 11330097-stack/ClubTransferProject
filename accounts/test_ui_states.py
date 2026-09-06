from django.test import Client, TestCase, override_settings
from django.urls import path, reverse

from club_transfer.urls import urlpatterns as project_urlpatterns

from .models import User


def forced_server_error(request):
    raise RuntimeError('internal detail must not be rendered')


urlpatterns = [
    path('__state-test__/server-error/', forced_server_error),
] + project_urlpatterns

handler403 = 'club_transfer.error_views.permission_denied'
handler404 = 'club_transfer.error_views.page_not_found'
handler500 = 'club_transfer.error_views.server_error'


@override_settings(DEBUG=False, ROOT_URLCONF='accounts.test_ui_states')
class ErrorExperienceTests(TestCase):
    def test_authenticated_permission_denial_uses_product_error_page(self):
        student = User.objects.create_user(
            username='state-student', password='password', role='student',
        )
        self.client.force_login(student)

        response = self.client.get(reverse('account_admin_list'))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, '您沒有權限查看此頁面', status_code=403)
        self.assertContains(response, '返回儀表板', status_code=403)

    def test_missing_resource_uses_product_404_page(self):
        response = self.client.get('/this-page-does-not-exist/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, '找不到您要查看的頁面', status_code=404)
        self.assertNotContains(response, 'Page not found at', status_code=404)

    def test_unhandled_exception_uses_safe_product_500_page(self):
        self.client.raise_request_exception = False

        response = self.client.get('/__state-test__/server-error/')

        self.assertEqual(response.status_code, 500)
        self.assertContains(response, '這次操作沒有完成', status_code=500)
        self.assertNotContains(response, 'internal detail must not be rendered', status_code=500)

    def test_csrf_failure_explains_that_the_change_was_not_submitted(self):
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(reverse('login'), {'username': 'x', 'password': 'x'})

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, '此頁面已失效，操作未送出', status_code=403)
        self.assertContains(response, '系統沒有執行這次變更', status_code=403)


class UiStateContractTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='state-admin', password='password', role='admin',
        )
        self.client.force_login(self.admin)

    def test_account_import_is_csv_only_and_standalone_creation_remains(self):
        import_response = self.client.get(reverse('account_admin_import'))

        self.assertContains(import_response, '匯入帳號 CSV')
        self.assertNotContains(import_response, '新增單一帳號')
        self.assertNotContains(import_response, 'name="create_one"')
        self.assertEqual(self.client.get(reverse('account_admin_create')).status_code, 200)

    def test_account_list_distinguishes_empty_data_from_no_results(self):
        empty_response = self.client.get(reverse('account_admin_list'))
        filtered_response = self.client.get(reverse('account_admin_list'), {'q': 'missing'})

        self.assertContains(empty_response, '目前沒有可管理的帳號')
        self.assertContains(filtered_response, '找不到符合篩選條件的帳號')
        self.assertContains(filtered_response, '清除篩選條件')

    def test_bulk_student_action_without_selection_explains_recovery(self):
        response = self.client.post(reverse('student_admin_bulk_deactivate'), follow=True)

        self.assertContains(response, '請先選取要停用的學生。')
        self.assertContains(response, 'alert-warning')
