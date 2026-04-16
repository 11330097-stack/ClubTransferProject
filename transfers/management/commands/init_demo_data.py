"""
初始化演示資料的命令
使用方法: python manage.py init_demo_data
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import User
from clubs.models import Club


class Command(BaseCommand):
    help = '初始化演示資料（社團和測試使用者）'

    def handle(self, *args, **kwargs):
        with transaction.atomic():
            self.stdout.write('正在建立演示資料...')
            
            # 建立社團（先不設社長和老師，等使用者建立後再更新）
            clubs_data = [
                {'name': '籃球社', 'description': '熱愛籃球運動，培養團隊合作精神', 'max_members': 25},
                {'name': '吉他社', 'description': '學習吉他演奏技巧，分享音樂樂趣', 'max_members': 20},
                {'name': '攝影社', 'description': '探索攝影藝術，記錄美好瞬間', 'max_members': 15},
                {'name': '程式設計社', 'description': '學習程式設計，開發創新專案', 'max_members': 30},
                {'name': '桌遊社', 'description': '各類桌遊活動，增進邏輯思維', 'max_members': 20},
                {'name': '舞蹈社', 'description': '多元舞蹈風格，展現自我風采', 'max_members': 25},
            ]
            
            clubs = []
            for data in clubs_data:
                club, created = Club.objects.get_or_create(name=data['name'], defaults=data)
                clubs.append(club)
                if created:
                    self.stdout.write(f'  建立社團: {club.name}')
                else:
                    self.stdout.write(f'  社團已存在: {club.name}')
            
            # 建立指導老師
            teachers = []
            for i, club in enumerate(clubs[:3], 1):
                teacher, created = User.objects.get_or_create(
                    username=f'teacher{i}',
                    defaults={
                        'first_name': f'老師{i}',
                        'email': f'teacher{i}@school.edu.tw',
                        'role': 'teacher',
                    }
                )
                if created:
                    teacher.set_password('teacher123')
                    teacher.save()
                    self.stdout.write(f'  建立老師: {teacher.first_name} (帳號: teacher{i}, 密碼: teacher123)')
                teachers.append(teacher)
            
            # 建立社長
            presidents = []
            for i, club in enumerate(clubs[:4], 1):
                president, created = User.objects.get_or_create(
                    username=f'president{i}',
                    defaults={
                        'first_name': f'社長{i}',
                        'email': f'president{i}@school.edu.tw',
                        'role': 'president',
                        'club': club,
                    }
                )
                if created:
                    president.set_password('president123')
                    president.save()
                    self.stdout.write(f'  建立社長: {president.first_name} (帳號: president{i}, 密碼: president123)')
                presidents.append(president)
            
            # 建立學生
            students = []
            for i in range(1, 6):
                student, created = User.objects.get_or_create(
                    username=f'student{i}',
                    defaults={
                        'first_name': f'學生{i}',
                        'email': f'student{i}@school.edu.tw',
                        'role': 'student',
                        'student_id': f'2024{i:03d}',
                        'club': clubs[i % len(clubs)],
                    }
                )
                if created:
                    student.set_password('student123')
                    student.save()
                    # 更新社團人數
                    student.club.current_members += 1
                    student.club.save()
                    self.stdout.write(f'  建立學生: {student.first_name} (帳號: student{i}, 密碼: student123)')
                students.append(student)
            
            # 更新社團的社長和老師
            for i, club in enumerate(clubs):
                if i < len(teachers):
                    club.teacher = teachers[i]
                if i < len(presidents):
                    club.president = presidents[i]
                club.save()
            
            # 建立管理員
            admin, created = User.objects.get_or_create(
                username='admin',
                defaults={
                    'first_name': '訓育組',
                    'email': 'admin@school.edu.tw',
                    'role': 'admin',
                    'is_staff': True,
                    'is_superuser': True,
                }
            )
            if created:
                admin.set_password('admin123')
                admin.save()
                self.stdout.write(f'  建立管理員: {admin.first_name} (帳號: admin, 密碼: admin123)')
            else:
                self.stdout.write(f'  管理員已存在: admin')
            
            self.stdout.write(self.style.SUCCESS('演示資料建立完成！'))
            self.stdout.write('\n測試帳號清單：')
            self.stdout.write('  - 管理員: admin / admin123')
            self.stdout.write('  - 社長: president1~4 / president123')
            self.stdout.write('  - 老師: teacher1~3 / teacher123')
            self.stdout.write('  - 學生: student1~5 / student123')
