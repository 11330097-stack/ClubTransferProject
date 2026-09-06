from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from clubs.models import Club
from transfers.models import TransferRequest, TransferWindow

from .models import User


class RoleDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='dashboard-admin', password='password', role='admin', first_name='管理員',
        )
        cls.club = Club.objects.create(
            code='DASH1', name='儀表板社團', max_members=3,
        )
        cls.target_club = Club.objects.create(
            code='DASH2', name='目標社團', max_members=2,
        )
        cls.other_club = Club.objects.create(
            code='DASH3', name='其他社團', max_members=5,
        )
        cls.president = User.objects.create_user(
            username='dashboard-president', role='president', first_name='社長甲', club=cls.club,
        )
        cls.target_president = User.objects.create_user(
            username='target-president', role='president', first_name='社長乙', club=cls.target_club,
        )
        cls.other_president = User.objects.create_user(
            username='other-president', role='president', first_name='社長丙', club=cls.other_club,
        )
        cls.teacher = User.objects.create_user(
            username='dashboard-teacher', role='teacher', first_name='老師甲',
        )
        cls.other_teacher = User.objects.create_user(
            username='other-teacher', role='teacher', first_name='老師乙',
        )
        cls.student = User.objects.create_user(
            username='dashboard-student', role='student', student_id='D001',
            first_name='學生甲', club=cls.club,
        )
        cls.second_student = User.objects.create_user(
            username='dashboard-student-2', role='student', student_id='D002',
            first_name='學生乙', club=cls.club,
        )
        cls.unassigned_student = User.objects.create_user(
            username='dashboard-unassigned', role='student', student_id='D003',
            first_name='未分配學生',
        )
        cls.club.president = '社長甲 (dashboard-president)'
        cls.club.teacher = '老師甲 (dashboard-teacher)'
        cls.club.save(update_fields=['president', 'teacher'])
        cls.target_club.president = '社長乙 (target-president)'
        cls.target_club.teacher = '老師乙 (other-teacher)'
        cls.target_club.save(update_fields=['president', 'teacher'])
        cls.other_club.president = '社長丙 (other-president)'
        cls.other_club.teacher = '老師乙 (other-teacher)'
        cls.other_club.save(update_fields=['president', 'teacher'])
        today = timezone.localdate()
        cls.window = TransferWindow.objects.create(
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=5),
        )

    def get_home(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('home'))

    def test_assigned_student_without_request_sees_apply_next_action(self):
        response = self.get_home(self.student)

        self.assertContains(response, '學生工作區')
        self.assertContains(response, self.club.name)
        self.assertContains(response, '提出轉社申請')
        self.assertNotContains(response, '營運總覽')

    def test_student_pending_and_returned_states_render_correct_cta(self):
        request = TransferRequest.objects.create(
            student=self.student,
            original_club=self.club,
            target_club=self.target_club,
            status='orig_president_pending',
        )
        pending_response = self.get_home(self.student)
        self.assertContains(pending_response, '申請正在審核')
        self.assertContains(pending_response, request.get_status_display())

        request.status = 'returned'
        request.save(update_fields=['status'])
        returned_response = self.get_home(self.student)
        self.assertContains(returned_response, '需要重新選擇目標社團')
        self.assertContains(returned_response, reverse('reselect_club', args=[request.pk]))

    def test_unassigned_student_gets_clear_blocked_state(self):
        response = self.get_home(self.unassigned_student)

        self.assertContains(response, '目前尚未分配社團')
        apply_cta = (
            f'<a href="{reverse("transfer_apply")}" class="btn btn-primary">'
            '提出轉社申請</a>'
        )
        self.assertNotContains(response, apply_cta, html=True)

    def test_closed_window_explains_why_student_cannot_apply(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.window.start_date = yesterday - timedelta(days=2)
        self.window.end_date = yesterday
        self.window.save()

        response = self.get_home(self.student)

        self.assertContains(response, '目前不能提出新申請')
        self.assertContains(response, '本次申請期間已結束')

    def test_student_approved_and_rejected_requests_show_terminal_state(self):
        approved = TransferRequest.objects.create(
            student=self.student,
            original_club=self.club,
            target_club=self.target_club,
            status='approved',
        )
        self.student.club = self.target_club
        self.student.save(update_fields=['club'])
        approved_response = self.get_home(self.student)
        self.assertContains(approved_response, '申請已完成，請依學校安排至新社團報到')

        approved.delete()
        TransferRequest.objects.create(
            student=self.student,
            original_club=self.target_club,
            target_club=self.club,
            status='rejected',
        )
        rejected_response = self.get_home(self.student)
        self.assertContains(rejected_response, '本次申請已結束')
        self.assertContains(rejected_response, '重新提出轉社申請')
        self.assertContains(rejected_response, reverse('transfer_apply'))

    def test_president_sees_only_authorized_pending_requests_and_capacity(self):
        relevant = TransferRequest.objects.create(
            student=self.student,
            original_club=self.club,
            target_club=self.target_club,
            status='orig_president_pending',
        )
        outsider = User.objects.create_user(
            username='dashboard-outsider', role='student', student_id='D004',
            first_name='不應顯示學生', club=self.other_club,
        )
        TransferRequest.objects.create(
            student=outsider,
            original_club=self.other_club,
            target_club=self.target_club,
            status='orig_president_pending',
        )

        response = self.get_home(self.president)

        self.assertContains(response, '社長工作區')
        self.assertContains(response, relevant.student.first_name)
        self.assertContains(response, '剩餘名額')
        self.assertContains(response, '已額滿')
        self.assertNotContains(response, outsider.first_name)

    def test_president_with_remaining_capacity_sees_all_clear_state(self):
        self.club.max_members = 5
        self.club.save(update_fields=['max_members'])

        response = self.get_home(self.president)

        self.assertContains(response, '目前沒有待審核申請')
        self.assertContains(response, '剩餘 2 名')

    def test_president_without_club_has_safe_fallback(self):
        no_club_president = User.objects.create_user(
            username='president-without-club', role='president', first_name='無社團社長',
        )
        response = self.get_home(no_club_president)

        self.assertContains(response, '找不到有效的社團責任')

    def test_teacher_sees_assigned_club_and_only_teacher_stage_work(self):
        request = TransferRequest.objects.create(
            student=self.student,
            original_club=self.club,
            target_club=self.target_club,
            status='orig_teacher_pending',
        )

        response = self.get_home(self.teacher)

        self.assertContains(response, '指導老師工作區')
        self.assertContains(response, self.club.name)
        self.assertContains(response, request.student.first_name)
        self.assertNotContains(response, '營運總覽')

    def test_teacher_without_assigned_club_has_empty_state(self):
        teacher = User.objects.create_user(
            username='teacher-without-club', role='teacher', first_name='未指派老師',
        )
        response = self.get_home(teacher)

        self.assertContains(response, '尚未指派負責社團')

    def test_teacher_with_assigned_club_sees_all_clear_state(self):
        response = self.get_home(self.teacher)

        self.assertContains(response, self.club.name)
        self.assertContains(response, '目前沒有待審核申請')

    def test_admin_sees_operational_counts_and_capacity_attention(self):
        TransferRequest.objects.create(
            student=self.student,
            original_club=self.club,
            target_club=self.target_club,
            status='admin_pending',
        )

        response = self.get_home(self.admin)

        self.assertContains(response, '歡迎來到社團轉社系統')
        self.assertNotContains(
            response,
            '優先處理最終核定、未分配學生與社團容量，再進行日常帳號及社團管理。',
        )
        self.assertContains(response, '1 筆申請等待訓育組最終核定')
        self.assertContains(response, '1 位學生尚未分配社團')
        self.assertContains(response, self.club.name)
        self.assertContains(response, '100%')
        self.assertContains(response, '待最終核定')
        self.assertContains(response, '距離截止還有 5 天')

    def test_admin_no_work_and_closed_window_states_are_explicit(self):
        self.unassigned_student.club = self.other_club
        self.unassigned_student.save(update_fields=['club'])
        yesterday = timezone.localdate() - timedelta(days=1)
        self.window.start_date = yesterday - timedelta(days=2)
        self.window.end_date = yesterday
        self.window.save()

        response = self.get_home(self.admin)

        self.assertContains(response, '目前沒有待處理項目')
        self.assertContains(response, '本次申請期間已結束')
