from django import forms
from django.db.models import Q

from clubs.models import Club
from transfers.models import get_user_from_display_text
from .models import User


def format_user_display_text(user):
    display_name = user.get_full_name() or user.first_name or user.username
    return f'{display_name} ({user.username})'


def normalize_teacher_text(value):
    return ' '.join((value or '').split())


def get_teacher_match_values(teacher):
    full_name = normalize_teacher_text(teacher.get_full_name())
    first_name = normalize_teacher_text(teacher.first_name)
    username = normalize_teacher_text(teacher.username)
    display_name = full_name or first_name or username
    values = {
        username,
        first_name,
        full_name,
        normalize_teacher_text(str(teacher)),
    }
    if display_name and username:
        values.add(f'{display_name} ({username})')
    return {value for value in values if value}


class StudentAccountForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text='新增時必填；編輯時留空代表不修改密碼。',
    )

    class Meta:
        model = User
        fields = [
            'username',
            'student_id',
            'class_name',
            'seat_number',
            'first_name',
            'email',
            'role',
            'club',
            'is_active',
            'password',
        ]

    def __init__(self, *args, **kwargs):
        self.is_create = kwargs.pop('is_create', False)
        super().__init__(*args, **kwargs)
        self.original_password = self.instance.password
        self.fields['role'].choices = [('student', 'student')]
        self.fields['role'].initial = 'student'
        if self.instance.pk and self.instance.role == 'president':
            self.fields['role'].help_text = '儲存後會將此社長降級為一般學生。'
        self.fields['password'].required = self.is_create

    def clean_username(self):
        username = self.cleaned_data['username']
        queryset = User.objects.filter(username=username)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError('username 已存在。')
        return username

    def clean_student_id(self):
        student_id = self.cleaned_data['student_id']
        if not student_id:
            raise forms.ValidationError('student_id 必填。')
        queryset = User.objects.filter(student_id=student_id)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError('student_id 已存在。')
        return student_id

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'student'
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        elif user.pk:
            user.password = self.original_password
        if commit:
            user.save()
            self.save_m2m()
        return user


class ClubAdminForm(forms.ModelForm):
    teacher = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label='指導老師',
    )
    president = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label='社長',
    )

    class Meta:
        model = Club
        fields = [
            'code',
            'name',
            'teacher',
            'president',
            'location',
            'description',
            'max_members',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current_teacher = get_user_from_display_text(self.instance.teacher)
        current_president = get_user_from_display_text(self.instance.president)

        president_filter = Q(role='student', is_active=True, club__isnull=True)
        if current_president:
            president_filter |= Q(pk=current_president.pk)
            self.initial['president'] = current_president.pk
        self.fields['president'].queryset = User.objects.filter(
            president_filter,
        ).order_by('username')

        assigned_teacher_values = {
            normalize_teacher_text(value)
            for value in Club.objects.exclude(teacher='').values_list('teacher', flat=True)
            if normalize_teacher_text(value)
        }
        available_teacher_ids = [
            teacher.pk
            for teacher in User.objects.filter(role='teacher', is_active=True)
            if get_teacher_match_values(teacher).isdisjoint(assigned_teacher_values)
        ]
        if current_teacher:
            available_teacher_ids.append(current_teacher.pk)
            self.initial['teacher'] = current_teacher.pk
        self.fields['teacher'].queryset = User.objects.filter(
            pk__in=available_teacher_ids,
        ).order_by('username')

    def clean_teacher(self):
        teacher = self.cleaned_data['teacher']
        self.selected_teacher = teacher
        return format_user_display_text(teacher)

    def clean_president(self):
        president = self.cleaned_data['president']
        self.selected_president = president
        return format_user_display_text(president)


class StudentCsvImportForm(forms.Form):
    csv_file = forms.FileField(label='CSV 檔案')
