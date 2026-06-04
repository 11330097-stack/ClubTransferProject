import csv
import io

from django.db import transaction
from django.db.models import Q

from clubs.models import Club
from transfers.models import ApprovalLog, TransferRequest, get_user_from_display_text
from .models import User


REQUIRED_STUDENT_IMPORT_FIELDS = [
    'name',
    'role',
    'email',
    'class_name',
    'seat_number',
    'club_code',
    'password',
]

REQUIRED_CLUB_IMPORT_FIELDS = [
    'code',
    'name',
    'teacher_username',
    'president_username',
    'location',
    'max_members',
]

SAMPLE_STUDENT_IMPORT_CSV = (
    'name,role,email,class_name,seat_number,club_code,password\n'
    'Student One,student,student001@example.com,101,1,D001,student123\n'
    'Teacher One,teacher,teacher001@example.com,,,,teacher123'
)

SAMPLE_CLUB_IMPORT_CSV = (
    'code,name,teacher_username,president_username,location,max_members,description\n'
    'D001,Debate Club,teacher001,student001,Room 101,30,Weekly debate practice\n'
    'D002,Drama Club,,,Auditorium,25,'
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
            error = validate_account_import_row(cleaned)
            if error:
                result['skipped'] += 1
                result['errors'].append({'row': row_number, 'reason': error})
                continue

            club = None
            if cleaned['role'] == 'student' and cleaned['club_code']:
                club = Club.objects.filter(code=cleaned['club_code'], is_active=True).first()
                if club is None:
                    result['skipped'] += 1
                    result['errors'].append({
                        'row': row_number,
                        'reason': f'Active Club.code={cleaned["club_code"]} not found.',
                    })
                    continue

            user, created = resolve_account_import_user(cleaned)
            if created:
                user.username = generate_unique_username(cleaned['role'])
                if cleaned['role'] == 'student':
                    user.student_id = generate_unique_student_id()

            user.first_name = cleaned['name']
            user.email = cleaned['email']
            user.role = cleaned['role']
            user.is_active = True
            if cleaned['role'] == 'student':
                user.class_name = cleaned['class_name']
                user.seat_number = int(cleaned['seat_number'])
                user.club = club
            else:
                user.student_id = ''
                user.class_name = ''
                user.seat_number = None
                user.club = None
            user.set_password(cleaned['password'])
            user.save()

            if created:
                result['created'] += 1
            else:
                result['updated'] += 1

        recalculate_club_current_members()

    return result


def generate_unique_username(role):
    prefix = 'student' if role == 'student' else 'teacher'
    return generate_unique_value(prefix, 'username', width=3)


def generate_unique_student_id():
    return generate_unique_value('S', 'student_id', width=6)


def generate_unique_value(prefix, field_name, width):
    existing_values = set(
        User.objects.filter(**{f'{field_name}__startswith': prefix})
        .values_list(field_name, flat=True)
    )
    number = 1
    while True:
        value = f'{prefix}{number:0{width}d}'
        if value not in existing_values:
            return value
        number += 1


def validate_account_import_row(row):
    if not row['name']:
        return 'name is required.'
    if row['role'] not in ['student', 'teacher']:
        return 'role must be student or teacher.'
    if not row['password']:
        return 'password is required.'
    if row['role'] == 'student':
        if not row['class_name']:
            return 'class_name is required for student.'
        if not row['seat_number']:
            return 'seat_number is required for student.'
        try:
            seat_number = int(row['seat_number'])
        except ValueError:
            return 'seat_number must be an integer.'
        if seat_number < 1 or seat_number > 99:
            return 'seat_number must be between 1 and 99.'
    return None


def resolve_account_import_user(row):
    if row['email']:
        user = User.objects.filter(email=row['email'], role=row['role']).first()
        if user:
            return user, False
    return User(), True


def import_clubs_from_csv(csv_file):
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
        field for field in REQUIRED_CLUB_IMPORT_FIELDS
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
                for field in REQUIRED_CLUB_IMPORT_FIELDS
            }
            cleaned['description'] = (row.get('description') or '').strip()

            existing_club = Club.objects.filter(code=cleaned['code']).first()
            teacher, president, error = validate_club_import_row(cleaned, existing_club)
            if error:
                result['skipped'] += 1
                result['errors'].append({'row': row_number, 'reason': error})
                continue

            club, created = Club.objects.select_for_update().get_or_create(
                code=cleaned['code'],
                defaults={'name': cleaned['name']},
            )
            previous_president_ids = get_previous_president_ids(club)

            club.name = cleaned['name']
            club.teacher = format_import_user_display_text(teacher) if teacher else ''
            club.president = format_import_user_display_text(president) if president else ''
            club.location = cleaned['location']
            club.max_members = int(cleaned['max_members'])
            club.description = cleaned['description']
            club.is_active = True
            club.save(update_fields=[
                'name',
                'teacher',
                'president',
                'location',
                'max_members',
                'description',
                'is_active',
            ])

            if previous_president_ids:
                User.objects.filter(
                    pk__in=previous_president_ids,
                ).exclude(pk=president.pk if president else None).update(
                    role='student',
                    club=club,
                )

            if president:
                president = User.objects.select_for_update().get(pk=president.pk)
                president.role = 'president'
                president.club = club
                president.save(update_fields=['role', 'club'])

            if created:
                result['created'] += 1
            else:
                result['updated'] += 1

        recalculate_club_current_members()

    return result


def validate_club_import_row(row, existing_club=None):
    if not row['code']:
        return None, None, 'code is required.'
    if not row['name']:
        return None, None, 'name is required.'

    try:
        max_members = int(row['max_members'])
    except ValueError:
        return None, None, 'max_members must be a positive integer.'
    if max_members < 1:
        return None, None, 'max_members must be a positive integer.'

    teacher = None
    if row['teacher_username']:
        teacher = User.objects.filter(username=row['teacher_username']).first()
        if not teacher or teacher.role != 'teacher' or not teacher.is_active:
            return None, None, (
                f'teacher_username={row["teacher_username"]} must be an active teacher.'
            )

    president = None
    if row['president_username']:
        president = User.objects.filter(username=row['president_username']).first()
        is_current_president = (
            existing_club
            and president
            and president.role == 'president'
            and president.is_active
            and president.club_id == existing_club.pk
        )
        is_available_student = (
            president
            and president.role == 'student'
            and president.is_active
            and president.club_id is None
        )
        if not is_current_president and not is_available_student:
            return None, None, (
                f'president_username={row["president_username"]} '
                'must be an active unassigned student.'
            )

    return teacher, president, None


def get_previous_president_ids(club):
    if not club.pk:
        return []

    previous_president = get_user_from_display_text(club.president)
    previous_president_ids = list(
        User.objects.filter(club=club, role='president').values_list('pk', flat=True)
    )
    if previous_president and previous_president.role == 'president':
        previous_president_ids.append(previous_president.pk)
    return previous_president_ids


def format_import_user_display_text(user):
    display_name = user.get_full_name() or user.first_name or user.username
    return f'{display_name} ({user.username})'


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


def clear_president_assignment(student):
    if student.role == 'president':
        Club.objects.filter(president__icontains=f'({student.username})').update(president='')


def clear_teacher_assignment(teacher):
    if teacher.role != 'teacher':
        return

    teacher_values = [
        teacher.username,
        teacher.first_name,
        teacher.get_full_name(),
        format_import_user_display_text(teacher),
    ]
    query = Q(teacher__icontains=f'({teacher.username})')
    for value in {value for value in teacher_values if value}:
        query |= Q(teacher=value)
    Club.objects.filter(query).update(teacher='')


def deactivate_student(student):
    clear_president_assignment(student)
    if student.is_active:
        student.is_active = False
        student.save(update_fields=['is_active'])


def safely_delete_student(student):
    clear_president_assignment(student)

    if has_student_history(student):
        deactivate_student(student)
        return 'deactivated'

    student.delete()
    return 'deleted'


def deactivate_teacher(teacher):
    clear_teacher_assignment(teacher)
    if teacher.is_active:
        teacher.is_active = False
        teacher.save(update_fields=['is_active'])


def has_teacher_history(teacher):
    return ApprovalLog.objects.filter(approver=teacher).exists()


def safely_delete_teacher(teacher):
    clear_teacher_assignment(teacher)

    if has_teacher_history(teacher):
        deactivate_teacher(teacher)
        return 'deactivated'

    teacher.delete()
    return 'deleted'
