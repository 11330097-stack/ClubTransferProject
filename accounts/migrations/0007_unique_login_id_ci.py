from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0006_restore_password_account_identity'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(
                Lower('username'),
                name='unique_login_id_ci',
            ),
        ),
    ]
