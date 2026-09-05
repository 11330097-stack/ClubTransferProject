from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q

from clubs.models import Club
from transfers.models import get_user_from_display_text
from .models import User
from .services import (
    get_active_president_club,
    has_active_transfer,
    normalize_email,
    normalize_login_id,
)


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


def generate_unique_club_code():
    existing_codes = set(Club.objects.filter(code__startswith='C').values_list('code', flat=True))
    number = 1
    while True:
        code = f'C{number:03d}'
        if code not in existing_codes:
            return code
        number += 1


class StudentAccountForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label='新密碼',
        help_text='新增時必填；編輯時留空代表不修改密碼。',
    )
    password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label='確認新密碼',
    )

    class Meta:
        model = User
        fields = [
            'student_id',
            'class_name',
            'seat_number',
            'first_name',
            'email',
            'role',
            'club',
            'is_active',
            'password',
            'password_confirm',
        ]

    def __init__(self, *args, **kwargs):
        self.is_create = kwargs.pop('is_create', False)
        super().__init__(*args, **kwargs)
        self.original_role = self.instance.role
        self.original_password = self.instance.password
        if self.instance.pk and self.instance.role == 'president':
            self.fields['role'].choices = [('president', 'president')]
            self.fields['role'].initial = 'president'
        else:
            self.fields['role'].choices = [('student', 'student')]
            self.fields['role'].initial = 'student'
        self.fields['club'].queryset = Club.objects.filter(is_active=True).order_by('code', 'name')
        self.fields['password'].required = self.is_create
        self.fields['password_confirm'].required = self.is_create

    def clean_student_id(self):
        student_id = normalize_login_id(self.cleaned_data['student_id'])
        if not student_id:
            raise forms.ValidationError('學號必填。')
        queryset = User.objects.filter(student_id__iexact=student_id)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError('學號已存在。')
        username_matches = User.objects.filter(username__iexact=student_id)
        if self.instance.pk:
            username_matches = username_matches.exclude(pk=self.instance.pk)
        if username_matches.exists():
            raise forms.ValidationError('此學號已被其他登入帳號使用。')
        return student_id

    def clean_email(self):
        email = normalize_email(self.cleaned_data.get('email'))
        if email:
            queryset = User.objects.filter(email__iexact=email)
            if self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise forms.ValidationError('此 Email 已由其他帳號使用。')
        return email

    def clean(self):
        cleaned_data = super().clean()
        club = cleaned_data.get('club')
        if club and club.get_actual_member_count(exclude_user_id=self.instance.pk) >= club.max_members:
            self.add_error('club', '此社團人數已滿。')

        if self.instance.pk and get_active_president_club(self.instance):
            if not cleaned_data.get('is_active'):
                self.add_error('is_active', '啟用中社團的社長必須先完成社長交接。')
            if club and club.pk != self.instance.club_id:
                self.add_error('club', '社長必須先完成社長交接，不能直接更換社團。')
            if not club:
                self.add_error('club', '社長必須先完成社長交接，不能直接移出社團。')

        if (
            self.instance.pk
            and self.instance.club_id != (club.pk if club else None)
            and has_active_transfer(self.instance)
        ):
            self.add_error('club', '此學生有進行中的轉社申請，不能直接變更社團。')

        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        if password or password_confirm:
            if password != password_confirm:
                self.add_error('password_confirm', '兩次輸入的密碼不一致。')
            elif password:
                try:
                    validate_password(password, self.instance)
                except forms.ValidationError as error:
                    self.add_error('password', error)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        if not self.is_create and self.instance.pk:
            user.role = self.original_role
        else:
            user.role = 'student'
        user.username = user.student_id
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        elif not self.is_create:
            user.password = self.original_password
        if commit:
            user.save()
            self.save_m2m()
        return user


class TeacherAccountForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label='新密碼',
        help_text='新增時必填；編輯時留空代表不修改密碼。',
    )
    password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label='確認新密碼',
    )

    class Meta:
        model = User
        fields = [
            'username',
            'first_name',
            'email',
            'is_active',
            'password',
            'password_confirm',
        ]

    def __init__(self, *args, **kwargs):
        self.is_create = kwargs.pop('is_create', False)
        super().__init__(*args, **kwargs)
        self.original_password = self.instance.password
        self.fields['password'].required = self.is_create
        self.fields['password_confirm'].required = self.is_create

    def clean_username(self):
        username = normalize_login_id(self.cleaned_data['username'])
        queryset = User.objects.filter(username__iexact=username)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError('登入帳號已存在。')
        return username

    def clean_email(self):
        email = normalize_email(self.cleaned_data.get('email'))
        if email:
            queryset = User.objects.filter(email__iexact=email)
            if self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise forms.ValidationError('此 Email 已由其他帳號使用。')
        return email

    def clean_first_name(self):
        first_name = self.cleaned_data['first_name'].strip()
        if not first_name:
            raise forms.ValidationError('姓名必填。')
        return first_name

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        if password or password_confirm:
            if password != password_confirm:
                self.add_error('password_confirm', '兩次輸入的密碼不一致。')
            elif password:
                try:
                    validate_password(password, self.instance)
                except forms.ValidationError as error:
                    self.add_error('password', error)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'teacher'
        if self.is_create:
            user.is_active = True
        user.student_id = ''
        user.class_name = ''
        user.seat_number = None
        user.club = None
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        elif not self.is_create:
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
    password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label='確認新密碼',
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'email', 'password', 'password_confirm']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_password = self.instance.password

    def clean_username(self):
        username = normalize_login_id(self.cleaned_data['username'])
        queryset = User.objects.filter(username__iexact=username)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError('username 已存在。')
        return username

    def clean_email(self):
        email = normalize_email(self.cleaned_data.get('email'))
        if email:
            queryset = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
            if queryset.exists():
                raise forms.ValidationError('此 Email 已由其他帳號使用。')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        if password or password_confirm:
            if password != password_confirm:
                self.add_error('password_confirm', '兩次輸入的密碼不一致。')
            elif password:
                try:
                    validate_password(password, self.instance)
                except forms.ValidationError as error:
                    self.add_error('password', error)
        return cleaned_data

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
    login_id = forms.CharField(max_length=150, label='登入帳號／學生學號')
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
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        label='密碼',
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        label='確認密碼',
    )

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        login_id = normalize_login_id(cleaned_data.get('login_id'))
        cleaned_data['login_id'] = login_id
        if User.objects.filter(username__iexact=login_id).exists():
            self.add_error('login_id', '登入帳號已存在。')

        email = normalize_email(cleaned_data.get('email'))
        cleaned_data['email'] = email
        if email and User.objects.filter(email__iexact=email).exists():
            self.add_error('email', '此 Email 已由其他帳號使用。')

        if role == 'student':
            if User.objects.filter(student_id__iexact=login_id).exists():
                self.add_error('login_id', '學生學號已存在。')
            club = cleaned_data.get('club')
            if club and club.get_actual_member_count() >= club.max_members:
                self.add_error('club', '此社團人數已滿。')
        elif cleaned_data.get('club'):
            self.add_error('club', '老師帳號不能設定學生社團。')

        password = cleaned_data.get('password')
        if password != cleaned_data.get('password_confirm'):
            self.add_error('password_confirm', '兩次輸入的密碼不一致。')
        elif password:
            candidate = User(username=login_id, role=role or 'student')
            try:
                validate_password(password, candidate)
            except forms.ValidationError as error:
                self.add_error('password', error)
        return cleaned_data

    def save(self):
        role = self.cleaned_data['role']
        login_id = self.cleaned_data['login_id']
        user = User(
            username=login_id,
            role=role,
            first_name=self.cleaned_data['first_name'].strip(),
            email=self.cleaned_data.get('email', ''),
            is_active=True,
        )
        if role == 'student':
            user.student_id = login_id
            user.class_name = self.cleaned_data.get('class_name', '').strip()
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

    def clean(self):
        cleaned_data = super().clean()
        max_members = cleaned_data.get('max_members')
        president = getattr(self, 'selected_president', None)
        if max_members and president:
            existing_count = self.instance.get_actual_member_count() if self.instance.pk else 0
            added_president_count = int(not self.instance.pk or president.club_id != self.instance.pk)
            if existing_count + added_president_count > max_members:
                self.add_error(
                    'max_members',
                    '人數上限不可低於更新後的實際社員人數。',
                )
        return cleaned_data

    def save(self, commit=True):
        if not self.instance.pk and not self.instance.code:
            self.instance.code = generate_unique_club_code()
        return super().save(commit=commit)


class StudentCsvImportForm(forms.Form):
    csv_file = forms.FileField(
        label='CSV 檔案',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv,text/csv'}),
    )

    def clean_csv_file(self):
        csv_file = self.cleaned_data['csv_file']
        if not csv_file.name.lower().endswith('.csv'):
            raise forms.ValidationError('本系統不支援 .xlsx 檔案。請上傳 .csv 檔案。')
        return csv_file


class ClubCsvImportForm(forms.Form):
    csv_file = forms.FileField(label='CSV 檔案')
