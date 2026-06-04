from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from clubs.models import Club
from .models import TransferRequest, TransferWindow


class SuperuserTransferAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='superuser',
            password='password',
            email='superuser@example.com',
        )
        self.original_club = Club.objects.create(
            code='O001',
            name='Original Club',
            current_members=1,
        )
        self.target_club = Club.objects.create(
            code='T001',
            name='Target Club',
            current_members=0,
            max_members=30,
        )
        self.student = User.objects.create_user(
            username='transfer-student',
            role='student',
            club=self.original_club,
        )
        self.transfer_request = TransferRequest.objects.create(
            student=self.student,
            original_club=self.original_club,
            target_club=self.target_club,
            status='admin_pending',
        )
        self.client.force_login(self.superuser)

    def test_superuser_can_view_pending_and_all_requests(self):
        pending_response = self.client.get(reverse('pending_approvals'))
        all_response = self.client.get(reverse('all_requests'))

        self.assertEqual(pending_response.status_code, 200)
        self.assertContains(pending_response, self.student.username)
        self.assertEqual(all_response.status_code, 200)
        self.assertContains(all_response, self.student.username)

    def test_superuser_can_approve_admin_pending_request(self):
        response = self.client.post(
            reverse('approve_request', args=[self.transfer_request.pk]),
        )

        self.assertRedirects(response, reverse('pending_approvals'))
        self.transfer_request.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(self.transfer_request.status, 'approved')
        self.assertEqual(self.student.club, self.target_club)

    def test_superuser_can_approve_existing_request_when_window_is_paused(self):
        today = timezone.localdate()
        TransferWindow.objects.create(
            start_date=today,
            end_date=today,
            is_paused=True,
        )

        response = self.client.post(
            reverse('approve_request', args=[self.transfer_request.pk]),
        )

        self.assertRedirects(response, reverse('pending_approvals'))
        self.transfer_request.refresh_from_db()
        self.assertEqual(self.transfer_request.status, 'approved')

    def test_superuser_can_delete_request_record(self):
        response = self.client.post(
            reverse('delete_request_record', args=[self.transfer_request.pk]),
        )

        self.assertRedirects(response, reverse('all_requests'))
        self.assertFalse(
            TransferRequest.objects.filter(pk=self.transfer_request.pk).exists()
        )


class ReselectClubNotificationTests(TestCase):
    def test_reselect_sends_notification_after_returning_to_new_president_pending(self):
        original_club = Club.objects.create(code='O002', name='Original Club')
        target_club = Club.objects.create(code='T002', name='Target Club')
        new_target_club = Club.objects.create(code='T003', name='New Target Club')
        student = User.objects.create_user(
            username='reselect-student',
            password='password',
            role='student',
            club=original_club,
        )
        transfer_request = TransferRequest.objects.create(
            student=student,
            original_club=original_club,
            target_club=target_club,
            status='returned',
        )
        self.client.force_login(student)

        with patch.object(TransferRequest, 'send_notification') as send_notification:
            response = self.client.post(
                reverse('reselect_club', args=[transfer_request.pk]),
                {'target_club': new_target_club.pk},
            )

        self.assertRedirects(response, reverse('my_requests'))
        transfer_request.refresh_from_db()
        self.assertEqual(transfer_request.target_club, new_target_club)
        self.assertEqual(transfer_request.status, 'new_president_pending')
        send_notification.assert_called_once()


class TransferWindowPauseTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.original_club = Club.objects.create(
            code='PW001',
            name='Pause Window Original',
            current_members=1,
            max_members=30,
        )
        self.target_club = Club.objects.create(
            code='PW002',
            name='Pause Window Target',
            current_members=0,
            max_members=30,
        )
        self.student = User.objects.create_user(
            username='pause-student',
            password='password',
            role='student',
            club=self.original_club,
        )
        self.admin = User.objects.create_user(
            username='pause-admin',
            password='password',
            role='admin',
        )
        self.window = TransferWindow.objects.create(
            start_date=self.today,
            end_date=self.today,
        )

    def test_student_can_apply_when_window_is_open_and_not_paused(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse('transfer_apply'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.target_club.name)

    def test_student_cannot_apply_when_window_is_paused(self):
        self.window.is_paused = True
        self.window.save(update_fields=['is_paused'])
        self.client.force_login(self.student)

        response = self.client.get(reverse('transfer_apply'), follow=True)

        self.assertRedirects(response, reverse('home'))
        self.assertContains(response, '轉社申請目前暫停')

    def test_student_can_apply_after_window_is_resumed(self):
        self.window.is_paused = True
        self.window.save(update_fields=['is_paused'])
        self.client.force_login(self.admin)
        self.client.post(reverse('transfer_window_resume'))
        self.client.force_login(self.student)

        response = self.client.get(reverse('transfer_apply'))

        self.assertEqual(response.status_code, 200)

    def test_teacher_president_and_admin_still_cannot_apply(self):
        roles = ['teacher', 'president', 'admin']
        for role in roles:
            user = User.objects.create_user(
                username=f'{role}-cannot-apply',
                password='password',
                role=role,
                club=self.original_club,
            )
            self.client.force_login(user)

            response = self.client.get(reverse('transfer_apply'))

            self.assertNotEqual(response.status_code, 200)

    def test_admin_can_pause_and_resume_window_with_post(self):
        self.client.force_login(self.admin)

        pause_response = self.client.post(reverse('transfer_window_pause'))
        self.window.refresh_from_db()
        self.assertRedirects(pause_response, reverse('transfer_window_settings'))
        self.assertTrue(self.window.is_paused)

        resume_response = self.client.post(reverse('transfer_window_resume'))
        self.window.refresh_from_db()
        self.assertRedirects(resume_response, reverse('transfer_window_settings'))
        self.assertFalse(self.window.is_paused)

    def test_pause_and_resume_urls_do_not_change_state_with_get(self):
        self.client.force_login(self.admin)

        pause_response = self.client.get(reverse('transfer_window_pause'))
        resume_response = self.client.get(reverse('transfer_window_resume'))
        self.window.refresh_from_db()

        self.assertEqual(pause_response.status_code, 405)
        self.assertEqual(resume_response.status_code, 405)
        self.assertFalse(self.window.is_paused)
