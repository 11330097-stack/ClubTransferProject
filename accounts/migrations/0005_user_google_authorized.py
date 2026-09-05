from django.db import migrations, models
from django.db.models.functions import Lower


def disable_legacy_password_login(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    for user in User.objects.filter(is_superuser=False).exclude(role='admin').iterator():
        user.password = '!'
        user.google_authorized = False
        user.save(update_fields=['password', 'google_authorized'])


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0004_user_class_name_user_seat_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='google_authorized',
            field=models.BooleanField(
                default=False,
                help_text='僅限由管理員匯入並授權的學生或老師帳號。',
                verbose_name='已授權 Google 登入',
            ),
        ),
        migrations.RunPython(
            disable_legacy_password_login,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(
                Lower('email'),
                condition=models.Q(google_authorized=True),
                name='unique_authorized_google_email_ci',
            ),
        ),
    ]
