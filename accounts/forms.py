from django import forms

from .models import User


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
            'first_name',
            'email',
            'phone',
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


class StudentCsvImportForm(forms.Form):
    csv_file = forms.FileField(label='CSV 檔案')
