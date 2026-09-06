import random

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from accounts.services import recalculate_club_current_members
from clubs.models import Club
from transfers.models import TransferRequest


USER_PREFIX = 'ui8_'
CLUB_CODE_PREFIX = 'UI8C'
SEED = 20260906
REGULAR_STUDENT_COUNT = 75
PRESIDENT_COUNT = 10
TEACHER_COUNT = 15
CLUB_COUNT = 10
UNASSIGNED_STUDENT_COUNT = 12
TEST_PASSWORD = 'UI8-Local-Test-2026!'


class Command(BaseCommand):
    help = 'Create, inspect, or remove the deterministic Requirement 8 UI test dataset.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['create', 'status', 'remove'])

    def handle(self, *args, **options):
        action = options['action']
        if action == 'create':
            self.create_dataset()
        elif action == 'remove':
            self.remove_dataset()
        else:
            self.print_status()

    def marker_querysets(self):
        return (
            User.objects.filter(username__startswith=USER_PREFIX),
            Club.objects.filter(code__startswith=CLUB_CODE_PREFIX),
        )

    def create_dataset(self):
        test_users, test_clubs = self.marker_querysets()
        if test_users.exists() or test_clubs.exists():
            raise CommandError(
                'UI8 test data already exists. Run "manage.py ui_test_data remove" first.'
            )

        rng = random.Random(SEED)
        password_hash = make_password(TEST_PASSWORD)
        categories = ['academic', 'arts', 'performance', 'recreation', 'sports']
        capacities = [12, 10, 12, 14, 18, 20, 8, 16, 20, 15]
        occupancies = [12, 9, 8, 7, 7, 6, 6, 5, 4, 9]

        with transaction.atomic():
            teachers = [
                User(
                    username=f'ui8_teacher_{number:03d}',
                    first_name=(
                        f'UI8 Test Teacher {number:03d} With Extended Synthetic Name'
                        if number in [7, 15]
                        else f'UI8 Test Teacher {number:03d}'
                    ),
                    email=f'ui8.teacher.{number:03d}@example.invalid',
                    role='teacher',
                    is_active=True,
                    password=password_hash,
                )
                for number in range(1, TEACHER_COUNT + 1)
            ]
            User.objects.bulk_create(teachers)
            teachers = list(
                User.objects.filter(username__startswith='ui8_teacher_').order_by('username')
            )

            clubs = [
                Club(
                    code=f'{CLUB_CODE_PREFIX}{number:02d}',
                    name=(
                        f'UI8 Test Club {number:02d} — Extended Synthetic Club Name for Wrapping Audit'
                        if number in [3, 8]
                        else f'UI8 Test Club {number:02d}'
                    ),
                    teacher=f'UI8 Teacher {number:02d} ({teachers[number - 1].username})',
                    location=(
                        f'UI8 Synthetic Campus Building {number}, Multi-purpose Activity Room'
                        if number in [4, 9]
                        else f'UI8 Test Room {100 + number}'
                    ),
                    category=categories[(number - 1) % len(categories)],
                    description=(
                        'UI8 synthetic club description used only for responsive, wrapping, '
                        'accessibility, and realistic-data verification.'
                    ),
                    max_members=capacities[number - 1],
                    current_members=0,
                    is_active=True,
                )
                for number in range(1, CLUB_COUNT + 1)
            ]
            Club.objects.bulk_create(clubs)
            clubs = list(Club.objects.filter(code__startswith=CLUB_CODE_PREFIX).order_by('code'))

            presidents = []
            for index, club in enumerate(clubs, start=1):
                number = REGULAR_STUDENT_COUNT + index
                presidents.append(
                    User(
                        username=f'ui8_student_{number:03d}',
                        student_id=f'UI8S{number:03d}',
                        first_name=f'UI8 Test Student {number:03d}',
                        email=f'ui8.student.{number:03d}@example.invalid',
                        class_name=f'UI8-{((number - 1) % 3) + 1}0{((number - 1) % 4) + 1}',
                        seat_number=((number - 1) % 40) + 1,
                        role='president',
                        club=club,
                        is_active=True,
                        password=password_hash,
                    )
                )
            User.objects.bulk_create(presidents)
            presidents = list(
                User.objects.filter(
                    username__startswith='ui8_student_', role='president',
                ).select_related('club').order_by('username')
            )
            president_by_club_id = {president.club_id: president for president in presidents}
            for club in clubs:
                president = president_by_club_id[club.pk]
                club.president = f'{president.first_name} ({president.username})'
            Club.objects.bulk_update(clubs, ['president'])

            assignment_slots = []
            for club, occupancy in zip(clubs, occupancies):
                assignment_slots.extend([club] * (occupancy - 1))
            rng.shuffle(assignment_slots)

            regular_students = []
            for number in range(1, REGULAR_STUDENT_COUNT + 1):
                club = assignment_slots[number - 1] if number <= len(assignment_slots) else None
                regular_students.append(
                    User(
                        username=f'ui8_student_{number:03d}',
                        student_id=f'UI8S{number:03d}',
                        first_name=(
                            f'UI8 Test Student {number:03d} With An Intentionally Long Synthetic Name'
                            if number in [17, 34, 51, 68]
                            else f'UI8 Test Student {number:03d}'
                        ),
                        email=(
                            f'ui8.student.{number:03d}.long-address-for-wrapping-audit@example.invalid'
                            if number in [19, 38, 57]
                            else f'ui8.student.{number:03d}@example.invalid'
                        ),
                        class_name=f'UI8-{((number - 1) % 3) + 1}0{((number - 1) % 4) + 1}',
                        seat_number=((number - 1) % 40) + 1,
                        role='student',
                        club=club,
                        is_active=True,
                        password=password_hash,
                    )
                )
            User.objects.bulk_create(regular_students)
            recalculate_club_current_members()

        self.stdout.write(self.style.SUCCESS('Created deterministic UI8 test data.'))
        self.print_status()

    def remove_dataset(self):
        test_users, test_clubs = self.marker_querysets()
        with transaction.atomic():
            transfer_count = TransferRequest.objects.filter(
                student__username__startswith=USER_PREFIX,
            ).count()
            user_count = test_users.count()
            club_count = test_clubs.count()
            test_users.delete()
            test_clubs.delete()

        self.stdout.write(self.style.SUCCESS(
            f'Removed {user_count} UI8 users, {club_count} UI8 clubs, '
            f'and {transfer_count} UI8 transfer requests.'
        ))

    def print_status(self):
        test_users, test_clubs = self.marker_querysets()
        student_accounts = test_users.filter(role__in=['student', 'president'])
        assigned_students = student_accounts.filter(club__isnull=False)
        self.stdout.write(
            'UI8 status: '
            f'users={test_users.count()}, '
            f'student_accounts={student_accounts.count()}, '
            f'regular_students={test_users.filter(role="student").count()}, '
            f'presidents={test_users.filter(role="president").count()}, '
            f'teachers={test_users.filter(role="teacher").count()}, '
            f'clubs={test_clubs.count()}, '
            f'assigned_students={assigned_students.count()}, '
            f'unassigned_students={student_accounts.filter(club__isnull=True).count()}, '
            f'teacher_assignments={test_clubs.exclude(teacher="").count()}, '
            f'transfer_requests={TransferRequest.objects.filter(student__username__startswith=USER_PREFIX).count()}'
        )
