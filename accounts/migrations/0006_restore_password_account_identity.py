from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0005_user_google_authorized'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='user',
            name='unique_authorized_google_email_ci',
        ),
        migrations.RemoveField(
            model_name='user',
            name='google_authorized',
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(
                Lower('email'),
                condition=~models.Q(email=''),
                name='unique_nonempty_email_ci',
            ),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(
                Lower('student_id'),
                condition=(
                    models.Q(role__in=['student', 'president'])
                    & ~models.Q(student_id='')
                ),
                name='unique_student_id_ci',
            ),
        ),
    ]
