import csv
import io

from django.db import transaction

from clubs.models import Club
from .models import User


REQUIRED_STUDENT_IMPORT_FIELDS = [
    'username',
    'student_id',
    'name',
    'email',
    'phone',
    'club_code',
    'password',
]

SAMPLE_STUDENT_IMPORT_CSV = (
    'username,student_id,name,email,phone,club_code,password\n'
    'student001,2026001,Student One,student001@example.com,0912345678,D001,student123\n'
    'student002,2026002,Student Two,student002@example.com,0922333444,D002,student123'
)


def import_students_from_csv(csv_file):
    result = {
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'errors': [],
    }

    try:
        decoded = csv_file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        result['errors'].append({'row': '-', 'reason': 'CSV must use UTF-8 encoding.'})
        return result

    reader = csv.DictReader(io.StringIO(decoded))
    missing_fields = [
        field for field in REQUIRED_STUDENT_IMPORT_FIELDS
        if field not in (reader.fieldnames or [])
    ]
    if missing_fields:
        result['errors'].append({
            'row': '-',
            'reason': f'Missing CSV fields: {", ".join(missing_fields)}',
        })
        return result

    with transaction.atomic():
        for row_number, row in enumerate(reader, start=2):
            cleaned = {
                field: (row.get(field) or '').strip()
                for field in REQUIRED_STUDENT_IMPORT_FIELDS
            }
            error = validate_student_import_row(cleaned)
            if error:
                result['skipped'] += 1
                result['errors'].append({'row': row_number, 'reason': error})
                continue

            club = Club.objects.filter(code=cleaned['club_code']).first()
            if club is None:
                result['skipped'] += 1
                result['errors'].append({
                    'row': row_number,
                    'reason': f'Club.code={cleaned["club_code"]} not found.',
                })
                continue

            user, created, error = resolve_student_import_user(cleaned)
            if error:
                result['skipped'] += 1
                result['errors'].append({'row': row_number, 'reason': error})
                continue

            if created and not cleaned['password']:
                result['skipped'] += 1
                result['errors'].append({
                    'row': row_number,
                    'reason': 'Password is required for new accounts.',
                })
                continue

            user.username = cleaned['username']
            user.student_id = cleaned['student_id']
            user.first_name = cleaned['name']
            user.email = cleaned['email']
            user.phone = cleaned['phone']
            user.club = club
            user.role = 'student'
            user.is_active = True
            if cleaned['password']:
                user.set_password(cleaned['password'])
            user.save()

            if created:
                result['created'] += 1
            else:
                result['updated'] += 1

        recalculate_club_current_members()

    return result


def validate_student_import_row(row):
    required_values = ['username', 'student_id', 'name', 'club_code']
    for field in required_values:
        if not row[field]:
            return f'{field} is required.'
    return None


def resolve_student_import_user(row):
    username_user = User.objects.filter(username=row['username']).first()
    student_id_users = User.objects.filter(student_id=row['student_id'])
    student_id_count = student_id_users.count()

    if student_id_count > 1:
        return None, False, f'student_id={row["student_id"]} already maps to multiple accounts.'

    student_id_user = student_id_users.first()

    if username_user and student_id_user and username_user.pk != student_id_user.pk:
        return None, False, (
            f'username={row["username"]} and student_id={row["student_id"]} '
            'map to different accounts.'
        )

    if username_user:
        return username_user, False, None

    if student_id_user:
        return student_id_user, False, None

    return User(), True, None


def recalculate_club_current_members():
    for club in Club.objects.all():
        club.current_members = User.objects.filter(
            role__in=['student', 'president'],
            club=club,
            is_active=True,
        ).count()
        club.save(update_fields=['current_members'])
