"""
Initialize deterministic demo data.

Usage:
    python manage.py init_demo_data
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from django.db import transaction

from accounts.models import User
from clubs.models import Club


TOTAL_STUDENTS = 345
REGULAR_CLUB_COUNT = 23
STUDENTS_PER_REGULAR_CLUB = 14
DEFAULT_STUDENT_PASSWORD = "student123"


DEMO_CLUBS = [
    {"code": "D001", "name": "籃球社", "category": "sports", "location": "體育館", "max_members": 30},
    {"code": "D002", "name": "排球社", "category": "sports", "location": "排球場", "max_members": 30},
    {"code": "D003", "name": "羽球社", "category": "sports", "location": "活動中心", "max_members": 30},
    {"code": "D004", "name": "桌球社", "category": "sports", "location": "桌球教室", "max_members": 30},
    {"code": "D005", "name": "田徑社", "category": "sports", "location": "操場", "max_members": 30},
    {"code": "D006", "name": "吉他社", "category": "performance", "location": "音樂教室", "max_members": 30},
    {"code": "D007", "name": "熱音社", "category": "performance", "location": "練團室", "max_members": 30},
    {"code": "D008", "name": "合唱社", "category": "performance", "location": "合唱教室", "max_members": 30},
    {"code": "D009", "name": "舞蹈社", "category": "performance", "location": "韻律教室", "max_members": 30},
    {"code": "D010", "name": "美術社", "category": "arts", "location": "美術教室", "max_members": 30},
    {"code": "D011", "name": "攝影社", "category": "arts", "location": "攝影教室", "max_members": 30},
    {"code": "D012", "name": "書法社", "category": "arts", "location": "書法教室", "max_members": 30},
    {"code": "D013", "name": "手作社", "category": "arts", "location": "家政教室", "max_members": 30},
    {"code": "D014", "name": "資訊研究社", "category": "academic", "location": "電腦教室", "max_members": 30},
    {"code": "D015", "name": "程式設計社", "category": "academic", "location": "電腦教室", "max_members": 30},
    {"code": "D016", "name": "數理研究社", "category": "academic", "location": "數學教室", "max_members": 30},
    {"code": "D017", "name": "自然科學社", "category": "academic", "location": "實驗室", "max_members": 30},
    {"code": "D018", "name": "英語會話社", "category": "academic", "location": "語言教室", "max_members": 30},
    {"code": "D019", "name": "辯論社", "category": "academic", "location": "會議室", "max_members": 30},
    {"code": "D020", "name": "志工服務社", "category": "recreation", "location": "社團辦公室", "max_members": 30},
    {"code": "D021", "name": "康輔社", "category": "recreation", "location": "活動中心", "max_members": 30},
    {"code": "D022", "name": "桌遊社", "category": "recreation", "location": "多功能教室", "max_members": 30},
    {"code": "D023", "name": "棋藝社", "category": "recreation", "location": "棋藝教室", "max_members": 30},
    {"code": "D024", "name": "戲劇社", "category": "performance", "location": "表演教室", "max_members": 30},
]


class Command(BaseCommand):
    help = "初始化 Demo 社團資料與 student001~student345 學生帳號"

    def handle(self, *args, **kwargs):
        with transaction.atomic():
            clubs = self.create_demo_clubs()
            created_count, updated_count = self.create_demo_students(clubs)
            self.update_current_members(clubs)

        self.stdout.write(self.style.SUCCESS("Demo data initialized."))
        self.stdout.write(f"  Clubs: {len(clubs)}")
        self.stdout.write(f"  Students created: {created_count}")
        self.stdout.write(f"  Students updated: {updated_count}")
        self.stdout.write("  Student accounts: student001 ~ student345")
        self.stdout.write(f"  Student password: {DEFAULT_STUDENT_PASSWORD}")
        self.stdout.write("  Distribution:")
        for club in clubs:
            self.stdout.write(f"    - {club.name}: {club.current_members}")

    def create_demo_clubs(self):
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
                        "max_members": data["max_members"],
                        "current_members": 0,
                        "is_active": True,
                    },
                )
            else:
                club.name = data["name"]
                club.category = data["category"]
                club.location = data["location"]
                club.max_members = data["max_members"]
                club.is_active = True
                if not club.description:
                    club.description = f"{data['name']} Demo 社團資料"
                club.save()

            clubs.append(club)

        return clubs

    def create_demo_students(self, clubs):
        created_count = 0
        updated_count = 0
        password_hash = make_password(DEFAULT_STUDENT_PASSWORD)

        for i in range(1, TOTAL_STUDENTS + 1):
            assigned_club = self.get_assigned_club(i, clubs)
            username = f"student{i:03d}"

            student, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": f"學生{i:03d}",
                    "email": f"{username}@school.edu.tw",
                    "role": "student",
                    "student_id": f"2026{i:03d}",
                    "phone": f"09{i:08d}"[-10:],
                    "club": assigned_club,
                    "is_active": True,
                },
            )

            student.first_name = f"學生{i:03d}"
            student.email = f"{username}@school.edu.tw"
            student.role = "student"
            student.student_id = f"2026{i:03d}"
            student.phone = f"09{i:08d}"[-10:]
            student.club = assigned_club
            student.is_active = True
            student.password = password_hash
            student.save()

            if created:
                created_count += 1
            else:
                updated_count += 1

        return created_count, updated_count

    def get_assigned_club(self, student_number, clubs):
        regular_student_count = REGULAR_CLUB_COUNT * STUDENTS_PER_REGULAR_CLUB

        if student_number <= regular_student_count:
            club_index = (student_number - 1) // STUDENTS_PER_REGULAR_CLUB
            return clubs[club_index]

        return clubs[-1]

    def update_current_members(self, clubs):
        for club in clubs:
            club.current_members = User.objects.filter(
                role="student",
                club=club,
                is_active=True,
            ).count()
            club.save(update_fields=["current_members"])
