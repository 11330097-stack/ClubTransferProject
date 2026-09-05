"""
從 clubs.txt 匯入社團資料的命令
使用方法: python manage.py import_clubs_from_txt
"""
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from clubs.models import Club


class Command(BaseCommand):
    help = '從 clubs.txt 匯入大直高中社團資料'

    def get_category_from_code(self, code):
        """根據社團代號判斷類別"""
        if code.startswith('H1'):
            return 'academic'
        elif code.startswith('H2'):
            return 'arts'
        elif code.startswith('H3'):
            return 'performance'
        elif code.startswith('H4'):
            return 'recreation'
        elif code.startswith('H5'):
            return 'sports'
        return ''

    def handle(self, *args, **kwargs):
        file_path = 'clubs.txt'
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'找不到檔案: {file_path}'))
            return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'讀取檔案時發生錯誤: {e}'))
            return

        # 解析每一行資料
        pattern = r'代號:\s*([A-Z0-9]+),\s*社團名稱:\s*([^,]+),\s*指導老師:\s*([^,]+),\s*社長:\s*([^,]+),\s*場地:\s*(.+)'
        matches = re.findall(pattern, content)
        
        if not matches:
            self.stdout.write(self.style.WARNING('沒有找到任何社團資料'))
            return

        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for code, name, teacher, president, location in matches:
                # 清理空白字符
                code = code.strip()
                name = name.strip()
                teacher = teacher.strip()
                president = president.strip()
                location = location.strip()
                
                # 判斷類別
                category = self.get_category_from_code(code)
                
                # 建立或更新社團
                club, created = Club.objects.get_or_create(
                    code=code,
                    defaults={
                        'name': name,
                        'teacher': '',
                        'president': '',
                        'location': location,
                        'category': category,
                        'max_members': 30,
                        'current_members': 0,
                        'is_active': False,
                    }
                )
                
                if created:
                    created_count += 1
                    self.stdout.write(f'  建立: {code} - {name} ({category})')
                else:
                    # 更新現有資料
                    club.name = name
                    club.location = location
                    club.category = category
                    club.save(update_fields=['name', 'location', 'category'])
                    updated_count += 1
                    self.stdout.write(f'  更新: {code} - {name} ({category})')

        self.stdout.write(self.style.SUCCESS(
            f'\n匯入完成！共建立 {created_count} 個社團，更新 {updated_count} 個社團。'
        ))
        self.stdout.write(
            '新社團預設為停用；請在社團管理指派有效社長與指導老師後再啟用。'
        )
