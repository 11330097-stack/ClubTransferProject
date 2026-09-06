import csv
import io

from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q

from clubs.models import Club
from transfers.models import ApprovalLog, TransferRequest, get_user_from_display_text
from .models import User


REQUIRED_STUDENT_IMPORT_FIELDS = [
    'role',
    'login_id',
    'name',
    'email',
    'class_name',
    'seat_number',
    'club_name',
    'password',
]

REQUIRED_CLUB_IMPORT_FIELDS = [
    'code',
    'name',
    'location',
    'max_members',
]

OPTIONAL_CLUB_IMPORT_FIELDS = [
    'teacher_email',
    'president_email',
    'teacher_username',
    'president_username',
    'description',
]

SAMPLE_STUDENT_IMPORT_CSV = (
    'role,login_id,name,email,class_name,seat_number,club_name,password\n'
    'student,s000001,測試學生,student@example.invalid,101,1,,Example-Student-937!\n'
    'teacher,teacher.demo,測試老師,teacher@example.invalid,,,,Example-Teacher-482!'
)

SAMPLE_CLUB_IMPORT_CSV = (
    'code,name,teacher_username,president_username,location,max_members,description\n'
    'C001,籃球社,teacher.demo,s000001,體育館,30,籃球訓練與比賽'
)
ACTIVE_TRANSFER_STATUSES = [
    'orig_president_pending',
    'orig_teacher_pending',
    'new_president_pending',
    'new_teacher_pending',
    'admin_pending',
    'returned',
]


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
        result['errors'].append({'row': '-', 'reason': 'CSV 檔案必須使用 UTF-8 編碼。'})
        return result

    reader = csv.DictReader(io.StringIO(decoded))
    missing_fields = [
        field for field in REQUIRED_STUDENT_IMPORT_FIELDS
        if field not in (reader.fieldnames or [])
    ]
    if missing_fields:
        result['errors'].append({
            'row': '-',
            'reason': f'CSV 缺少必要欄位：{", ".join(missing_fields)}。',
        })
        return result

    seen_login_ids = set()
    seen_emails = set()
    with transaction.atomic():
        for row_number, row in enumerate(reader, start=2):
            cleaned = {
                field: (row.get(field) or '').strip()
                for field in REQUIRED_STUDENT_IMPORT_FIELDS
            }
            cleaned, error = validate_account_import_row(cleaned)
            if error:
                result['skipped'] += 1
                result['errors'].append({'row': row_number, 'reason': error})
                continue

            if cleaned['login_id'] in seen_login_ids:
                result['skipped'] += 1
                result['errors'].append({
                    'row': row_number,
                    'reason': '同一份 CSV 中的 login_id 重複。',
                })
                continue
            if cleaned['email'] and cleaned['email'] in seen_emails:
                result['skipped'] += 1
                result['errors'].append({
                    'row': row_number,
                    'reason': '同一份 CSV 中的 email 重複。',
                })
                continue

            user, created, error = resolve_account_import_user(cleaned)
            if error:
                result['skipped'] += 1
                result['errors'].append({'row': row_number, 'reason': error})
                continue

            club = None
            if cleaned['role'] == 'student' and cleaned['club_name']:
                club = Club.objects.select_for_update().filter(
                    name=cleaned['club_name'], is_active=True
                ).first()
                if club is None:
                    result['skipped'] += 1
                    result['errors'].append({
                        'row': row_number,
                        'reason': f'找不到啟用中的社團「{cleaned["club_name"]}」。',
                    })
                    continue

            if (
                not created
                and cleaned['role'] == 'student'
                and user.club_id != (club.pk if club else None)
                and has_active_transfer(user)
            ):
                result['skipped'] += 1
                result['errors'].append({
                    'row': row_number,
                    'reason': '學生有進行中的轉社申請，目前不能變更所屬社團。',
                })
                continue

            if club:
                assigned_count = club.get_actual_member_count(
                    exclude_user_id=user.pk if user.pk else None
                )
                if assigned_count >= club.max_members:
                    result['skipped'] += 1
                    result['errors'].append({
                        'row': row_number,
                        'reason': f'社團「{club.name}」已額滿。',
                    })
                    continue

            save_result = save_imported_account(user, created, cleaned, club)
            if save_result['error']:
                result['skipped'] += 1
                result['errors'].append({
                    'row': row_number,
                    'reason': save_result['error'],
                })
                continue

            if created:
                result['created'] += 1
            else:
                result['updated'] += 1
            seen_login_ids.add(cleaned['login_id'])
            if cleaned['email']:
                seen_emails.add(cleaned['email'])

        recalculate_club_current_members()

    return result


def normalize_email(value):
    return (value or '').strip().lower()


def normalize_login_id(value):
    return (value or '').strip().lower()


def validate_account_import_row(row):
    if row['role'] not in ['student', 'teacher']:
        return None, 'role 只接受 student 或 teacher；社長資料請從社團管理流程更新。'

    login_id = normalize_login_id(row['login_id'])
    if not login_id:
        return None, 'login_id 為必填欄位。'
    if len(login_id) > User._meta.get_field('username').max_length:
        return None, 'login_id 超過允許長度。'

    if not row['name']:
        return None, 'name 為必填欄位。'

    email = normalize_email(row['email'])
    if email:
        try:
            validate_email(email)
        except ValidationError:
            return None, 'email 格式不正確。'

    if row['role'] == 'student':
        if len(login_id) > User._meta.get_field('student_id').max_length:
            return None, '學生 login_id 超過學號欄位允許長度。'
        if row.get('seat_number'):
            try:
                seat_number = int(row['seat_number'])
            except ValueError:
                return None, 'seat_number 必須是整數。'
            if seat_number < 1 or seat_number > 99:
                return None, 'seat_number 必須介於 1 到 99。'
    elif row.get('club_name'):
        return None, '老師資料列不能設定 club_name。'

    cleaned = dict(row)
    cleaned['login_id'] = login_id
    cleaned['email'] = email
    return cleaned, None


def resolve_account_import_user(row):
    username_matches = list(
        User.objects.select_for_update().filter(username__iexact=row['login_id'])
    )
    if len(username_matches) > 1:
        return None, False, 'login_id 對應到多個帳號，無法安全更新。'
    user = username_matches[0] if username_matches else None

    if row['role'] == 'student':
        student_matches = list(
            User.objects.select_for_update().filter(student_id__iexact=row['login_id'])
        )
        if len(student_matches) > 1:
            return None, False, '學號對應到多個帳號，無法安全更新。'
        if student_matches and user and student_matches[0].pk != user.pk:
            return None, False, 'login_id 與學號對應到不同帳號。'
        if student_matches and not user:
            return None, False, '此學號已由其他登入帳號使用。'

    if row['email']:
        email_matches = list(
            User.objects.select_for_update().filter(email__iexact=row['email'])
        )
        if len(email_matches) > 1:
            return None, False, 'email 對應到多個帳號，無法安全更新。'
        if email_matches and (not user or email_matches[0].pk != user.pk):
            return None, False, '此 email 已由其他帳號使用。'

    if user:
        if user.is_superuser or user.role == 'admin':
            return None, False, '管理員帳號不能透過帳號匯入更新。'
        compatible = (
            (row['role'] == 'student' and user.role in ['student', 'president'])
            or (row['role'] == 'teacher' and user.role == 'teacher')
        )
        if not compatible:
            return None, False, '既有帳號的身分與匯入資料不相容。'
        if user.role == 'president':
            return None, False, '社長帳號必須從社團管理流程更新。'
        return user, False, None

    return User(username=row['login_id'], role=row['role']), True, None


def save_imported_account(user, created, row, club):
    password = row['password']
    if created and not password:
        return {'error': '建立新帳號時 password 為必填欄位。'}
    if password:
        try:
            validate_password(password, user)
        except ValidationError as error:
            return {'error': '密碼不符合安全要求：' + ' '.join(error.messages)}

    user.username = row['login_id']
    user.first_name = row['name'].strip()
    user.email = row['email']
    user.is_active = True
    if row['role'] == 'student':
        if user.role != 'president':
            user.role = 'student'
        user.student_id = row['login_id']
        user.class_name = row['class_name'].strip()
        user.seat_number = int(row['seat_number']) if row['seat_number'] else None
        user.club = club
    else:
        user.role = 'teacher'
        user.student_id = ''
        user.class_name = ''
        user.seat_number = None
        user.club = None
    if password:
        user.set_password(password)

    try:
        with transaction.atomic():
            user.save()
    except IntegrityError:
        return {'error': '帳號與既有的 login_id、學號或 email 衝突。'}
    return {'error': None}


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
        result['errors'].append({'row': '-', 'reason': 'CSV 檔案必須使用 UTF-8 編碼。'})
        return result

    reader = csv.DictReader(io.StringIO(decoded))
    missing_fields = [
        field for field in REQUIRED_CLUB_IMPORT_FIELDS
        if field not in (reader.fieldnames or [])
    ]
    if missing_fields:
        result['errors'].append({
            'row': '-',
            'reason': f'CSV 缺少必要欄位：{", ".join(missing_fields)}。',
        })
        return result

    seen_codes = set()
    with transaction.atomic():
        for row_number, row in enumerate(reader, start=2):
            cleaned = {
                field: (row.get(field) or '').strip()
                for field in REQUIRED_CLUB_IMPORT_FIELDS + OPTIONAL_CLUB_IMPORT_FIELDS
            }

            if cleaned['code'] in seen_codes:
                result['skipped'] += 1
                result['errors'].append({
                    'row': row_number,
                    'reason': '同一份 CSV 中的社團 code 重複。',
                })
                continue

            existing_club = Club.objects.filter(code=cleaned['code']).first()
            teacher, president, error = validate_club_import_row(cleaned, existing_club)
            if error:
                result['skipped'] += 1
                result['errors'].append({'row': row_number, 'reason': error})
                continue

            if existing_club:
                club = Club.objects.select_for_update().get(pk=existing_club.pk)
                created = False
            else:
                club = Club.objects.create(
                    code=cleaned['code'],
                    name=cleaned['name'],
                )
                created = True
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
            seen_codes.add(cleaned['code'])

        recalculate_club_current_members()

    return result


def validate_club_import_row(row, existing_club=None):
    if not row['code']:
        return None, None, 'code 為必填欄位。'
    if not row['name']:
        return None, None, 'name 為必填欄位。'

    try:
        max_members = int(row['max_members'])
    except ValueError:
        return None, None, 'max_members 必須是大於 0 的整數。'
    if max_members < 1:
        return None, None, 'max_members 必須是大於 0 的整數。'

    teacher = None
    teacher_identity = row.get('teacher_email') or row.get('teacher_username')
    if not teacher_identity:
        return None, None, '啟用中的社團必須設定 teacher。'
    teacher = (
        User.objects.filter(email__iexact=teacher_identity).first()
        if row.get('teacher_email')
        else User.objects.filter(username__iexact=teacher_identity).first()
    )
    if not teacher or teacher.role != 'teacher' or not teacher.is_active:
        return None, None, (
            f'找不到啟用中的指導老師「{teacher_identity}」。'
        )

    president = None
    president_identity = row.get('president_email') or row.get('president_username')
    if not president_identity:
        return None, None, '啟用中的社團必須設定 president。'
    president = (
        User.objects.filter(email__iexact=president_identity).first()
        if row.get('president_email')
        else User.objects.filter(username__iexact=president_identity).first()
    )
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
            f'社長「{president_identity}」必須是啟用中且尚未分配社團的學生。'
        )

    existing_member_count = existing_club.get_actual_member_count() if existing_club else 0
    added_president_count = int(not existing_club or president.club_id != existing_club.pk)
    if existing_member_count + added_president_count > max_members:
        return None, None, 'max_members 不可低於更新後的啟用中社員人數。'

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


def has_active_transfer(student):
    return TransferRequest.objects.filter(
        student=student,
        status__in=ACTIVE_TRANSFER_STATUSES,
    ).exists()


def clear_president_assignment(student):
    Club.objects.filter(
        Q(president__iexact=student.username)
        | Q(president__icontains=f'({student.username})')
    ).update(president='')


def get_active_president_club(student):
    query = Q(president__iexact=student.username) | Q(
        president__icontains=f'({student.username})'
    )
    if student.role == 'president' and student.club_id:
        query |= Q(pk=student.club_id)
    return Club.objects.filter(is_active=True).filter(query).first()


def get_valid_club_president(club):
    president = get_user_from_display_text(club.president)
    if (
        president
        and president.is_active
        and president.role == 'president'
        and president.club_id == club.pk
    ):
        return president
    return None


def get_valid_club_teacher(club):
    teacher = get_user_from_display_text(club.teacher)
    if teacher and teacher.is_active and teacher.role == 'teacher':
        return teacher
    return None


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
    if get_active_president_club(student):
        return 'president_requires_replacement'
    if has_active_transfer(student):
        return 'active_transfer_requires_resolution'
    clear_president_assignment(student)
    update_fields = []
    if student.role == 'president':
        student.role = 'student'
        student.club = None
        update_fields.extend(['role', 'club'])
    if student.is_active:
        student.is_active = False
        update_fields.append('is_active')
    if update_fields:
        student.save(update_fields=update_fields)
    return 'deactivated'


def safely_delete_student(student):
    if get_active_president_club(student):
        return 'president_requires_replacement'
    if has_active_transfer(student):
        return 'active_transfer_requires_resolution'

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
