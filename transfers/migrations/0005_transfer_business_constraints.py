from django.db import migrations, models


ACTIVE_STATUSES = [
    'orig_president_pending',
    'orig_teacher_pending',
    'new_president_pending',
    'new_teacher_pending',
    'admin_pending',
    'returned',
]


class Migration(migrations.Migration):
    dependencies = [
        ('transfers', '0004_transferrecordarchive_transferrecordsnapshot_and_more'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='transferrequest',
            constraint=models.UniqueConstraint(
                fields=('student',),
                condition=models.Q(status__in=ACTIVE_STATUSES),
                name='unique_active_transfer_per_student',
            ),
        ),
        migrations.AddConstraint(
            model_name='transferrequest',
            constraint=models.CheckConstraint(
                check=~models.Q(original_club=models.F('target_club')),
                name='transfer_clubs_must_differ',
            ),
        ),
    ]
