from datetime import timedelta
from io import StringIO
from unittest.mock import mock_open, patch

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from clubs.models import Club
from .models import ApprovalLog, TransferRequest, TransferWindow


class TransferWorkflowInvariantTests(TestCase):
    password = 'Valid-Audit-482!'

    def setUp(self):
        self.admin = User.objects.create_user(
            username='workflow-admin', password=self.password, role='admin'
        )
        self.original, self.original_president = self.make_club('WFO', max_members=10)
        self.target, self.target_president = self.make_club('WFT', max_members=10)
        self.student = User.objects.create_user(
            username='workflow-student', student_id='workflow-student',
            password=self.password, role='student', club=self.original, is_active=True,
        )
        self.recount(self.original)

    def make_club(self, code, max_members):
        president = User.objects.create_user(
            username=f'{code.lower()}-president', student_id=f'{code.lower()}-president',
            password=self.password, role='president', is_active=True,
        )
        club = Club.objects.create(
            code=code, name=f'{code} Club', max_members=max_members,
            president=f'President ({president.username})', is_active=True,
        )
        president.club = club
        president.save(update_fields=['club'])
        self.recount(club)
        return club, president

    def recount(self, club):
        club.current_members = User.objects.filter(
            club=club, role__in=['student', 'president'], is_active=True
        ).count()
        club.save(update_fields=['current_members'])

    def make_admin_pending(self):
        return TransferRequest.objects.create(
            student=self.student, original_club=self.original,
            target_club=self.target, status='admin_pending',
        )

    def test_stale_teacher_reference_does_not_grant_student_approval_power(self):
        former_teacher = User.objects.create_user(
            username='former-teacher', student_id='former-teacher',
            password=self.password, role='student', is_active=True,
        )
        self.original.teacher = 'Former Teacher (former-teacher)'
        self.original.save(update_fields=['teacher'])
        transfer_request = TransferRequest.objects.create(
            student=self.student, original_club=self.original,
            target_club=self.target, status='orig_teacher_pending',
        )
        self.client.force_login(former_teacher)

        self.client.post(reverse('approve_request', args=[transfer_request.pk]))

        transfer_request.refresh_from_db()
        self.assertEqual(transfer_request.status, 'orig_teacher_pending')
        self.assertFalse(ApprovalLog.objects.filter(transfer_request=transfer_request).exists())

    def test_stale_president_reference_does_not_expose_pending_request(self):
        unrelated_club, stale_president = self.make_club('WFS', max_members=10)
        self.original.president = f'Stale President ({stale_president.username})'
        self.original.save(update_fields=['president'])
        transfer_request = TransferRequest.objects.create(
            student=self.student, original_club=self.original,
            target_club=self.target, status='orig_president_pending',
        )
        self.client.force_login(stale_president)

        response = self.client.get(reverse('pending_approvals'))
        self.client.post(reverse('approve_request', args=[transfer_request.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(transfer_request, list(response.context['pending_requests']))
        transfer_request.refresh_from_db()
        self.assertEqual(transfer_request.status, 'orig_president_pending')

    def test_final_approval_rejects_inactive_target(self):
        transfer_request = self.make_admin_pending()
        self.target.is_active = False
        self.target.save(update_fields=['is_active'])
        self.client.force_login(self.admin)

        self.client.post(reverse('approve_request', args=[transfer_request.pk]))

        transfer_request.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(transfer_request.status, 'admin_pending')
        self.assertEqual(self.student.club, self.original)

    def test_final_approval_rejects_changed_student_membership(self):
        transfer_request = self.make_admin_pending()
        other, _ = self.make_club('WFX', max_members=10)
        self.student.club = other
        self.student.save(update_fields=['club'])
        self.client.force_login(self.admin)

        self.client.post(reverse('approve_request', args=[transfer_request.pk]))

        transfer_request.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(transfer_request.status, 'admin_pending')
        self.assertEqual(self.student.club, other)

    def test_final_approval_uses_actual_membership_not_stale_counter(self):
        transfer_request = self.make_admin_pending()
        self.target.max_members = 2
        self.target.current_members = 0
        self.target.save(update_fields=['max_members', 'current_members'])
        User.objects.create_user(
            username='target-filler', student_id='target-filler', password=self.password,
            role='student', club=self.target, is_active=True,
        )
        self.client.force_login(self.admin)

        self.client.post(reverse('approve_request', args=[transfer_request.pk]))

        transfer_request.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(transfer_request.status, 'admin_pending')
        self.assertEqual(self.student.club, self.original)

    def test_duplicate_final_submission_only_applies_once(self):
        transfer_request = self.make_admin_pending()
        self.client.force_login(self.admin)

        self.client.post(reverse('approve_request', args=[transfer_request.pk]))
        self.client.post(reverse('approve_request', args=[transfer_request.pk]))

        transfer_request.refresh_from_db()
        self.assertEqual(transfer_request.status, 'approved')
        self.assertEqual(
            ApprovalLog.objects.filter(
                transfer_request=transfer_request,
                approval_stage='admin_pending', result='approve',
            ).count(),
            1,
        )

    def test_application_rejects_inactive_original_club(self):
        TransferWindow.objects.create(
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=1),
        )
        self.original.is_active = False
        self.original.save(update_fields=['is_active'])
        self.client.force_login(self.student)

        self.client.post(reverse('transfer_apply'), {
            'target_club': self.target.pk, 'reason': 'audit',
        })

        self.assertFalse(TransferRequest.objects.filter(student=self.student).exists())

    def test_reselection_rejects_changed_membership(self):
        request = TransferRequest.objects.create(
            student=self.student, original_club=self.original,
            target_club=self.target, status='returned',
        )
        other, _ = self.make_club('WFY', max_members=10)
        new_target, _ = self.make_club('WFZ', max_members=10)
        self.student.club = other
        self.student.save(update_fields=['club'])
        self.client.force_login(self.student)

        self.client.post(reverse('reselect_club', args=[request.pk]), {
            'target_club': new_target.pk,
        })

        request.refresh_from_db()
        self.assertEqual(request.status, 'returned')
        self.assertEqual(request.target_club, self.target)

    def test_database_rejects_duplicate_active_requests(self):
        TransferRequest.objects.create(
            student=self.student, original_club=self.original,
            target_club=self.target, status='orig_president_pending',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TransferRequest.objects.create(
                    student=self.student, original_club=self.original,
                    target_club=self.target, status='admin_pending',
                )

    def test_database_rejects_same_original_and_target_club(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TransferRequest.objects.create(
                    student=self.student, original_club=self.original,
                    target_club=self.original, status='rejected',
                )

    def test_reject_after_approval_does_not_change_completed_request(self):
        transfer_request = self.make_admin_pending()
        self.client.force_login(self.admin)
        self.client.post(reverse('approve_request', args=[transfer_request.pk]))

        self.client.post(
            reverse('reject_request', args=[transfer_request.pk]),
            {'action': 'reject', 'comment': 'late'},
        )

        transfer_request.refresh_from_db()
        self.assertEqual(transfer_request.status, 'approved')
        self.assertFalse(
            ApprovalLog.objects.filter(
                transfer_request=transfer_request,
                result='reject',
            ).exists()
        )


class LegacyClubImportInvariantTests(TestCase):
    def test_text_import_creates_inactive_unassigned_club(self):
        content = '代號: H1001, 社團名稱: 稽核社, 指導老師: 純文字老師, 社長: 純文字社長, 場地: 教室'

        with patch('builtins.open', mock_open(read_data=content)):
            call_command('import_clubs_from_txt', stdout=StringIO())

        club = Club.objects.get(code='H1001')
        self.assertFalse(club.is_active)
        self.assertEqual(club.teacher, '')
        self.assertEqual(club.president, '')

    def test_text_import_does_not_overwrite_existing_assignments(self):
        club = Club.objects.create(
            code='H1002', name='Existing', teacher='Teacher (teacher-id)',
            president='President (president-id)', is_active=True,
        )
        content = '代號: H1002, 社團名稱: Updated, 指導老師: Other, 社長: Other, 場地: New Room'

        with patch('builtins.open', mock_open(read_data=content)):
            call_command('import_clubs_from_txt', stdout=StringIO())

        club.refresh_from_db()
        self.assertTrue(club.is_active)
        self.assertEqual(club.teacher, 'Teacher (teacher-id)')
        self.assertEqual(club.president, 'President (president-id)')
