"""
Initialize deterministic demo data.

Usage:
    python manage.py init_demo_data
"""
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from clubs.models import Club


TOTAL_STUDENT_ACCOUNTS = 345
CLUB_COUNT = 37
PRESIDENT_COUNT = 37
TEACHER_COUNT = 37
FIRST_GROUP_CLUB_COUNT = 12
FIRST_GROUP_STUDENT_MEMBERS = 9
SECOND_GROUP_STUDENT_MEMBERS = 8
STUDENT_PASSWORD = "student123"
TEACHER_PASSWORD = "teacher123"


def get_class_and_seat(student_number):
    zero_based = student_number - 1
    return str(101 + zero_based // 36), zero_based % 36 + 1


DEMO_CLUBS = [
    {"code": "D001", "name": "籃球社", "category": "sports", "location": "體育館"},
    {"code": "D002", "name": "排球社", "category": "sports", "location": "排球場"},
    {"code": "D003", "name": "羽球社", "category": "sports", "location": "活動中心"},
    {"code": "D004", "name": "桌球社", "category": "sports", "location": "桌球教室"},
    {"code": "D005", "name": "田徑社", "category": "sports", "location": "操場"},
    {"code": "D006", "name": "吉他社", "category": "performance", "location": "音樂教室"},
    {"code": "D007", "name": "熱音社", "category": "performance", "location": "練團室"},
    {"code": "D008", "name": "合唱社", "category": "performance", "location": "合唱教室"},
    {"code": "D009", "name": "舞蹈社", "category": "performance", "location": "韻律教室"},
    {"code": "D010", "name": "美術社", "category": "arts", "location": "美術教室"},
    {"code": "D011", "name": "攝影社", "category": "arts", "location": "攝影教室"},
    {"code": "D012", "name": "書法社", "category": "arts", "location": "書法教室"},
    {"code": "D013", "name": "手作社", "category": "arts", "location": "家政教室"},
    {"code": "D014", "name": "資訊研究社", "category": "academic", "location": "電腦教室"},
    {"code": "D015", "name": "程式設計社", "category": "academic", "location": "電腦教室"},
    {"code": "D016", "name": "數理研究社", "category": "academic", "location": "數學教室"},
    {"code": "D017", "name": "自然科學社", "category": "academic", "location": "實驗室"},
    {"code": "D018", "name": "英語會話社", "category": "academic", "location": "語言教室"},
    {"code": "D019", "name": "辯論社", "category": "academic", "location": "會議室"},
    {"code": "D020", "name": "志工服務社", "category": "recreation", "location": "社團辦公室"},
    {"code": "D021", "name": "康輔社", "category": "recreation", "location": "活動中心"},
    {"code": "D022", "name": "桌遊社", "category": "recreation", "location": "多功能教室"},
    {"code": "D023", "name": "棋藝社", "category": "recreation", "location": "棋藝教室"},
    {"code": "D024", "name": "戲劇社", "category": "performance", "location": "表演教室"},
    {"code": "D025", "name": "語文創作社", "category": "academic", "location": "語文教室"},
    {"code": "D026", "name": "數理研習社", "category": "academic", "location": "數學教室"},
    {"code": "D027", "name": "醫學研究社", "category": "academic", "location": "生物實驗室"},
    {"code": "D028", "name": "投資理財社", "category": "academic", "location": "社會科教室"},
    {"code": "D029", "name": "視覺藝術社", "category": "arts", "location": "美術教室"},
    {"code": "D030", "name": "動漫傳藝社", "category": "arts", "location": "多功能教室"},
    {"code": "D031", "name": "流行音樂社", "category": "performance", "location": "音樂教室"},
    {"code": "D032", "name": "街舞社", "category": "performance", "location": "韻律教室"},
    {"code": "D033", "name": "魔術社", "category": "performance", "location": "表演教室"},
    {"code": "D034", "name": "流行舞蹈社", "category": "performance", "location": "舞蹈教室"},
    {"code": "D035", "name": "擊樂社", "category": "performance", "location": "音樂教室"},
    {"code": "D036", "name": "網球社", "category": "sports", "location": "網球場"},
    {"code": "D037", "name": "棒壘球社", "category": "sports", "location": "操場"},
]


class Command(BaseCommand):
    help = "初始化 37 社團 Demo 帳號與社員分配"

    def handle(self, *args, **kwargs):
        with transaction.atomic():
            clubs = self.create_demo_clubs()
            student_created, student_updated = self.create_student_accounts(clubs)
            teacher_created, teacher_updated = self.create_teacher_accounts(clubs)
            self.update_current_members(clubs)

        self.stdout.write(self.style.SUCCESS("Demo data initialized."))
        self.stdout.write(f"  Clubs: {len(clubs)}")
        self.stdout.write(f"  Student accounts created: {student_created}")
        self.stdout.write(f"  Student accounts updated: {student_updated}")
        self.stdout.write(f"  Teacher accounts created: {teacher_created}")
        self.stdout.write(f"  Teacher accounts updated: {teacher_updated}")
        self.stdout.write("  Presidents: student001 ~ student037")
        self.stdout.write("  Students: student038 ~ student345")
        self.stdout.write("  Teachers: teacher001 ~ teacher037")
        self.stdout.write(f"  Student password: {STUDENT_PASSWORD}")
        self.stdout.write(f"  Teacher password: {TEACHER_PASSWORD}")
        self.stdout.write("  Distribution:")
        for club in clubs:
            self.stdout.write(
                f"    - {club.code} {club.name}: {club.current_members}, "
                f"president={club.president}, teacher={club.teacher}"
            )

    def create_demo_clubs(self):
        if len(DEMO_CLUBS) != CLUB_COUNT:
            raise ValueError(f"Expected {CLUB_COUNT} demo clubs, got {len(DEMO_CLUBS)}")

        clubs = []

        for data in DEMO_CLUBS:
            club = Club.objects.filter(code=data["code"]).first()

            if club is None:
                club = Club.objects.filter(name=data["name"]).first()

            if club is None:
                club, _ = Club.objects.get_or_create(
                    code=data["code"],
                    defaults={
                        "name": data["name"],
                        "category": data["category"],
                        "location": data["location"],
                        "description": f"{data['name']} Demo 社團資料",
                        "max_members": 30,
                        "current_members": 0,
                        "is_active": True,
                    },
                )
            else:
                club.code = data["code"]
                club.name = data["name"]
                club.category = data["category"]
                club.location = data["location"]
                club.max_members = 30
                club.is_active = True
                if not club.description:
                    club.description = f"{data['name']} Demo 社團資料"
                club.save()

            clubs.append(club)

        return clubs

    def create_student_accounts(self, clubs):
        created_count = 0
        updated_count = 0
        password_hash = make_password(STUDENT_PASSWORD)
        member_slots = self.build_member_slots(clubs)

        for i in range(1, TOTAL_STUDENT_ACCOUNTS + 1):
            username = f"student{i:03d}"
            class_name, seat_number = get_class_and_seat(i)

            if i <= PRESIDENT_COUNT:
                role = "president"
                assigned_club = clubs[i - 1]
            else:
                role = "student"
                assigned_club = member_slots[i - PRESIDENT_COUNT - 1]

            account, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": f"學生{i:03d}",
                    "email": f"{username}@school.edu.tw",
                    "role": role,
                    "student_id": f"2026{i:03d}",
                    "class_name": class_name,
                    "seat_number": seat_number,
                    "club": assigned_club,
                    "is_active": True,
                },
            )

            account.first_name = f"學生{i:03d}"
            account.email = f"{username}@school.edu.tw"
            account.role = role
            account.student_id = f"2026{i:03d}"
            account.class_name = class_name
            account.seat_number = seat_number
            account.club = assigned_club
            account.is_active = True
            account.password = password_hash
            account.save()

            if role == "president":
                assigned_club.president = f"{account.first_name} ({account.username})"
                assigned_club.save(update_fields=["president"])

            if created:
                created_count += 1
            else:
                updated_count += 1

        return created_count, updated_count

    def create_teacher_accounts(self, clubs):
        created_count = 0
        updated_count = 0
        password_hash = make_password(TEACHER_PASSWORD)

        for i, club in enumerate(clubs, start=1):
            username = f"teacher{i:03d}"
            teacher, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": f"老師{i:03d}",
                    "email": f"{username}@school.edu.tw",
                    "role": "teacher",
                    "student_id": "",
                    "club": None,
                    "is_active": True,
                },
            )

            teacher.first_name = f"老師{i:03d}"
            teacher.email = f"{username}@school.edu.tw"
            teacher.role = "teacher"
            teacher.student_id = ""
            teacher.club = None
            teacher.is_active = True
            teacher.password = password_hash
            teacher.save()

            club.teacher = f"{teacher.first_name} ({teacher.username})"
            club.save(update_fields=["teacher"])

            if created:
                created_count += 1
            else:
                updated_count += 1

        return created_count, updated_count

    def build_member_slots(self, clubs):
        slots = []

        for index, club in enumerate(clubs):
            if index < FIRST_GROUP_CLUB_COUNT:
                student_members = FIRST_GROUP_STUDENT_MEMBERS
            else:
                student_members = SECOND_GROUP_STUDENT_MEMBERS

            slots.extend([club] * student_members)

        expected_students = TOTAL_STUDENT_ACCOUNTS - PRESIDENT_COUNT
        if len(slots) != expected_students:
            raise ValueError(f"Expected {expected_students} student slots, got {len(slots)}")

        return slots

    def update_current_members(self, clubs):
        for club in clubs:
            club.current_members = User.objects.filter(
                role__in=["student", "president"],
                club=club,
                is_active=True,
            ).count()
            club.save(update_fields=["current_members"])
