from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    自定義使用者模型
    身分組：學生、社長、指導老師、訓育組（管理員）
    """
    ROLE_CHOICES = [
        ('student', '學生'),
        ('president', '社長'),
        ('teacher', '指導老師'),
        ('admin', '訓育組（管理員）'),
    ]
    
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='student',
        verbose_name='身分組'
    )
    student_id = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='學號'
    )
    club = models.ForeignKey(
        'clubs.Club',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='所屬社團',
        related_name='members'
    )
    phone = models.CharField(max_length=20, blank=True, verbose_name='電話')
    
    class Meta:
        verbose_name = '使用者'
        verbose_name_plural = '使用者'
    
    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"
    
    def is_student(self):
        return self.role == 'student'
    
    def is_president(self):
        return self.role == 'president'
    
    def is_teacher(self):
        return self.role == 'teacher'
    
    def is_admin(self):
        return self.role == 'admin'
