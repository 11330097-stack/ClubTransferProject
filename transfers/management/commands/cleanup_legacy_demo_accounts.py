from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from clubs.models import Club
from transfers.models import ApprovalLog, TransferRequest


LEGACY_USERNAMES = [
    "president1",
    "president2",
    "president3",
    "president4",
    "student1",
    "student2",
    "student3",
    "student4",
    "student5",
    "teacher1",
    "teacher2",
    "teacher3",
]


class Command(BaseCommand):
    help = "List or disable legacy demo accounts from the old demo dataset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Disable legacy demo accounts by setting is_active=False.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        users = {
            user.username: user
            for user in User.objects.filter(username__in=LEGACY_USERNAMES).order_by("username")
        }

        self.stdout.write(
            "Mode: apply" if apply_changes else "Mode: dry-run (no changes will be made)"
        )
        self.stdout.write("Target legacy accounts:")

        missing_usernames = []
        active_users = []

        for username in LEGACY_USERNAMES:
            user = users.get(username)

            if user is None:
                missing_usernames.append(username)
                self.stdout.write(f"  - {username}: missing")
                continue

            references = self.get_references(user)
            if user.is_active:
                active_users.append(user)

            self.stdout.write(
                "  - "
                f"{user.username}: role={user.role}, active={user.is_active}, "
                f"club={references['club']}, "
                f"club_president_refs={references['club_president_refs']}, "
                f"club_teacher_refs={references['club_teacher_refs']}, "
                f"transfer_requests={references['transfer_requests']}, "
                f"approval_logs={references['approval_logs']}"
            )

        if missing_usernames:
            self.stdout.write(f"Missing accounts: {len(missing_usernames)}")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run complete. {len(active_users)} active legacy accounts would be disabled."
                )
            )
            self.stdout.write("Run with --apply to set is_active=False for these accounts.")
            return

        with transaction.atomic():
            disabled_count = User.objects.filter(
                username__in=[user.username for user in active_users],
                is_active=True,
            ).update(is_active=False)

        self.stdout.write(
            self.style.SUCCESS(f"Disabled {disabled_count} legacy demo accounts.")
        )

        remaining_active = User.objects.filter(
            username__in=LEGACY_USERNAMES,
            is_active=True,
        ).count()
        self.stdout.write(f"Remaining active legacy accounts: {remaining_active}")

    def get_references(self, user):
        username_marker = f"({user.username})"

        return {
            "club": user.club.code if user.club else "-",
            "club_president_refs": Club.objects.filter(
                president__icontains=username_marker
            ).count(),
            "club_teacher_refs": Club.objects.filter(
                teacher__icontains=username_marker
            ).count(),
            "transfer_requests": TransferRequest.objects.filter(student=user).count(),
            "approval_logs": ApprovalLog.objects.filter(approver=user).count(),
        }
