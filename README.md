# 社團轉社電子化系統

基於 Django 開發的社團轉社申請與管理系統，實現線上申請、多階層審核、人數控管與自動化通知。

## 功能特性

- **線上申請與追蹤**: 一般學生可提交申請並查看審核進度；社長需先完成交接才能申請
- **多階層序位審核**: 原社長 → 原老師 → 新社長 → 新老師 → 訓育組
- **人數控管機制**: 自動限制超額申請，即時更新名額
- **透明資訊公告**: 首頁顯示各社團現有人數與剩餘名額
- **異常處理**: 退回重選機制，避免重新跑原社團流程
- **Email 通知**: 自動通知下一關審核者

## 系統需求

- Python 3.10+
- Django 4.2+

## 安裝與設定

### 1. 建立虛擬環境並安裝套件

```bash
# 使用 uv（推薦）
uv venv
uv pip install -r requirements.txt

# 或使用傳統 pip
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 資料庫遷移

```bash
python manage.py makemigrations
python manage.py migrate
```

### 3. 初始化演示資料

```bash
python manage.py init_demo_data
```

此指令會建立下方的學生、社長與指導老師帳號。訓育組帳號不會由此指令建立，如尚未建立請執行：

```bash
python manage.py createsuperuser
```

### 4. 啟動開發伺服器

```bash
python manage.py runserver
```

瀏覽器開啟 http://127.0.0.1:8000/

## Demo 帳號

| 角色 | 帳號 | 密碼 |
|------|------|------|
| 訓育組 / 管理員 | 自行建立的 superuser，或 `role='admin'` 的帳號 | 依建立時設定 |
| 社長 | student001 ~ student037 | student123 |
| 一般學生 | student038 ~ student345 | student123 |
| 指導老師 | teacher001 ~ teacher037 | teacher123 |

舊 demo 帳號 `president1~president4`、`student1~student5`、`teacher1~teacher3` 已停用，請不要用於展示流程。

## Demo 主流程範例

1. `student038` 以一般學生身分登入後送出轉社申請，例如從 D001 籃球社轉到 D002 排球社。`student001 ~ student037` 為社長，不能直接申請轉社。
2. `student001` 以原社團社長身分審核。
3. `teacher001` 以原社團指導老師身分審核。
4. `student002` 以新社團社長身分審核。
5. `teacher002` 以新社團指導老師身分審核。
6. 以自行建立的 superuser 或 `role='admin'` 的訓育組帳號做最終核准。

## 角色權限

| 功能 | 學生 | 社長 | 老師 | 訓育組 |
|------|:--:|:--:|:--:|:--:|
| 查看社團名額 | ✓ | ✓ | ✓ | ✓ |
| 提交轉社申請 | ✓ | | | |
| 查看申請進度 | ✓ | | | |
| 審核轉出/入 | | ✓ | ✓ | |
| 最終核定 | | | | ✓ |
| 設定人數上限 | | | | ✓ |
| 查看全校申請 | | | | ✓ |

## 專案結構

```
ClubTransferProject/
├── accounts/          # 使用者認證與管理
├── clubs/             # 社團管理
├── transfers/         # 轉社申請與審核
├── templates/         # HTML 模板
├── club_transfer/     # Django 設定
├── manage.py
└── requirements.txt
```

## 開發備註

- 郵件通知目前使用 Console Backend（開發時顯示在終端機）
- 生產環境請修改 `settings.py` 中的 `EMAIL_BACKEND` 設定
