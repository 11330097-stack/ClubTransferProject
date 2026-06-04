from django import forms
from django.db.models import Q

from clubs.models import Club
from transfers.models import get_user_from_display_text
from .models import User
from .services import generate_unique_student_id, generate_unique_username


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
        self.original_role = self.instance.role
        if self.instance.pk and self.instance.role == 'president':
            self.fields['role'].choices = [('president', 'president')]
            self.fields['role'].initial = 'president'
        else:
            self.fields['role'].choices = [('student', 'student')]
            self.fields['role'].initial = 'student'
        self.fields['password'].required = self.is_create
        if self.instance.pk:
            self.fields.pop('username', None)

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
        if not self.is_create and self.instance.pk:
            user.role = self.original_role
        else:
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


class TeacherAccountForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text='新增時必填；編輯時留空代表不修改密碼。',
    )

    class Meta:
        model = User
        fields = [
            'username',
            'first_name',
            'email',
            'is_active',
            'password',
        ]

    def __init__(self, *args, **kwargs):
        self.is_create = kwargs.pop('is_create', False)
        super().__init__(*args, **kwargs)
        self.original_password = self.instance.password
        self.fields['password'].required = self.is_create

    def clean_username(self):
        username = self.cleaned_data['username']
        queryset = User.objects.filter(username=username)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError('username 已存在。')
        return username

    def clean_first_name(self):
        first_name = self.cleaned_data['first_name'].strip()
        if not first_name:
            raise forms.ValidationError('姓名必填。')
        return first_name

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'teacher'
        if self.is_create:
            user.is_active = True
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        elif user.pk:
            user.password = self.original_password
        if commit:
            user.save()
            self.save_m2m()
        return user


class AdminProfileForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text='留空代表不修改密碼。',
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'email', 'password']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_password = self.instance.password

    def clean_username(self):
        username = self.cleaned_data['username']
        queryset = User.objects.filter(username=username)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError('username 已存在。')
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        else:
            user.password = self.original_password
        if commit:
            user.save()
        return user


class AccountCreateForm(forms.Form):
    role = forms.ChoiceField(
        choices=[('student', '學生'), ('teacher', '指導老師')],
        label='身分',
    )
    first_name = forms.CharField(label='姓名')
    email = forms.EmailField(required=False, label='Email')
    class_name = forms.CharField(required=False, label='班級')
    seat_number = forms.IntegerField(required=False, min_value=1, max_value=99, label='座號')
    club = forms.ModelChoiceField(
        queryset=Club.objects.filter(is_active=True).order_by('code', 'name'),
        required=False,
        label='社團',
        empty_label='未分配',
    )
    password = forms.CharField(widget=forms.PasswordInput, label='密碼')

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        if role == 'student':
            if not cleaned_data.get('class_name'):
                self.add_error('class_name', '學生必填班級。')
            if cleaned_data.get('seat_number') is None:
                self.add_error('seat_number', '學生必填座號。')
        return cleaned_data

    def save(self):
        role = self.cleaned_data['role']
        user = User(
            username=generate_unique_username(role),
            role=role,
            first_name=self.cleaned_data['first_name'],
            email=self.cleaned_data.get('email', ''),
            is_active=True,
        )
        if role == 'student':
            user.student_id = generate_unique_student_id()
            user.class_name = self.cleaned_data.get('class_name', '')
            user.seat_number = self.cleaned_data.get('seat_number')
            user.club = self.cleaned_data.get('club')
        user.set_password(self.cleaned_data['password'])
        user.save()
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


class ClubCsvImportForm(forms.Form):
    csv_file = forms.FileField(label='CSV 檔案')
