from django import forms

from .models import TransferWindow


class TransferWindowForm(forms.ModelForm):
    class Meta:
        model = TransferWindow
        fields = ['start_date', 'end_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }
        labels = {
            'start_date': '申請開放日期',
            'end_date': '申請截止日期',
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError('轉社開始日期不可晚於轉社結束日期。')

        return cleaned_data
