import csv
import io

from django.db import transaction
from django.db.models import Q

from clubs.models import Club
from transfers.models import ApprovalLog, TransferRequest
from .models import User


REQUIRED_STUDENT_IMPORT_FIELDS = [
    'username',
    'student_id',
    'class_name',
    'seat_number',
    'name',
    'email',
    'club_code',
    'password',
]

SAMPLE_STUDENT_IMPORT_CSV = (
    'username,student_id,class_name,seat_number,name,email,club_code,password\n'
    'student001,2026001,101,1,Student One,student001@example.com,D001,student123\n'
    'student002,2026002,101,2,Student Two,student002@example.com,D002,student123'
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
            user.class_name = cleaned['class_name']
            user.seat_number = int(cleaned['seat_number'])
            user.first_name = cleaned['name']
            user.email = cleaned['email']
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
    required_values = ['username', 'student_id', 'class_name', 'seat_number', 'name', 'club_code']
    for field in required_values:
        if not row[field]:
            return f'{field} is required.'
    try:
        seat_number = int(row['seat_number'])
    except ValueError:
        return 'seat_number must be an integer.'
    if seat_number < 1 or seat_number > 36:
        return 'seat_number must be between 1 and 36.'
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


def has_student_history(student):
    has_transfer_requests = TransferRequest.objects.filter(student=student).exists()
    has_approval_logs = ApprovalLog.objects.filter(
        Q(transfer_request__student=student) | Q(approver=student)
    ).exists()
    return has_transfer_requests or has_approval_logs


def safely_delete_student(student):
    if has_student_history(student):
        if student.is_active:
            student.is_active = False
            student.save(update_fields=['is_active'])
        return 'deactivated'

    student.delete()
    return 'deleted'
