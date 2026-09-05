from django.db import models


class Club(models.Model):
    """
    社團資料模型
    """
    CATEGORY_CHOICES = [
        ('academic', '學術類'),
        ('arts', '藝文類'),
        ('performance', '藝能類'),
        ('recreation', '康輔類'),
        ('sports', '體育類'),
    ]

    code = models.CharField(max_length=10, unique=True, null=True, blank=True, verbose_name='社團代號')
    name = models.CharField(max_length=100, verbose_name='社團名稱')
    teacher = models.CharField(max_length=50, default='', verbose_name='指導老師')
    president = models.CharField(max_length=50, default='', verbose_name='社長')
    location = models.CharField(max_length=100, blank=True, verbose_name='社課場地')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, blank=True, verbose_name='類別')
    description = models.TextField(blank=True, verbose_name='社團描述')
    max_members = models.PositiveIntegerField(default=30, verbose_name='人數上限')
    current_members = models.PositiveIntegerField(default=0, verbose_name='現有人數')
    is_active = models.BooleanField(default=True, verbose_name='啟用中')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='建立時間')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新時間')
    
    class Meta:
        verbose_name = '社團'
        verbose_name_plural = '社團'
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def has_available_slots(self):
        """檢查是否還有名額"""
        return self.get_actual_member_count() < self.max_members

    def get_actual_member_count(self, exclude_user_id=None):
        queryset = self.members.filter(
            role__in=['student', 'president'],
            is_active=True,
        )
        if exclude_user_id is not None:
            queryset = queryset.exclude(pk=exclude_user_id)
        return queryset.count()
    
    def get_remaining_slots(self):
        """取得剩餘名額"""
        return max(0, self.max_members - self.get_actual_member_count())
    
    def increment_members(self):
        """增加社員人數"""
        self.current_members += 1
        self.save()
    
    def decrement_members(self):
        """減少社員人數"""
        if self.current_members > 0:
            self.current_members -= 1
            self.save()
