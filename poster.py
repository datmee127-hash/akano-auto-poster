import os
import re
import json
import random
import requests
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timezone, timedelta

FB_TOKEN = os.environ["FB_PAGE_TOKEN"]
PAGE_ID  = "111199154354113"

# Vietnam timezone (UTC+7)
vn_tz        = timezone(timedelta(hours=7))
now          = datetime.now(vn_tz)
current_time = now.strftime("%H:%M")
print(f"[INFO] Giờ Việt Nam hiện tại: {current_time}")

# ── Google Auth ───────────────────────────────────────────────────────────────

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
creds      = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

# Google Sheet
gs_client   = gspread.authorize(creds)
spreadsheet = gs_client.open_by_key(os.environ["SHEET_ID"])
sheet       = spreadsheet.worksheet("Post")

# Google Drive
drive = build("drive", "v3", credentials=creds)

# ── Load folder map từ tab FOLDERS ────────────────────────────────────────────

def load_folder_map():
    try:
        folders_sheet = spreadsheet.worksheet("FOLDERS")
        records = folders_sheet.get_all_records()
        return {str(r.get("TÊN", "")).strip().lower(): str(r.get("FOLDER_ID", "")).strip()
                for r in records if r.get("TÊN") and r.get("FOLDER_ID")}
    except Exception as e:
        print(f"[WARN] Không đọc được tab FOLDERS: {e}")
        return {}

FOLDER_MAP = load_folder_map()
print(f"[INFO] Folder map: {FOLDER_MAP}")

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_direct_url(url):
    """Convert Google Drive share link → direct download URL."""
    if url and "drive.google.com" in url:
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if match:
            return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url


def random_image_from_folder(folder_name):
    """List ảnh trong Drive folder → random pick 1 → trả về bytes."""
    key       = folder_name.strip().lower()
    folder_id = FOLDER_MAP.get(key)
    if not folder_id:
        print(f"[ERROR] Không tìm thấy folder '{folder_name}' trong FOLDERS tab")
        return None

    result = drive.files().list(
        q=f"'{folder_id}' in parents and mimeType contains 'image/' and trashed=false",
        fields="files(id, name)",
        pageSize=100,
    ).execute()

    files = result.get("files", [])
    if not files:
        print(f"[ERROR] Folder '{folder_name}' không có ảnh")
        return None

    chosen = random.choice(files)
    print(f"[INFO] Random pick từ '{folder_name}': {chosen['name']}")

    # Download file từ Drive (dùng Drive API, không cần public link)
    file_bytes = drive.files().get_media(fileId=chosen["id"]).execute()
    return file_bytes


def download_image(url):
    """Download ảnh từ URL (hỗ trợ Google Drive share link)."""
    direct = get_direct_url(url)
    print(f"[INFO] Download ảnh: {direct}")

    session  = requests.Session()
    headers  = {"User-Agent": "Mozilla/5.0"}
    response = session.get(direct, headers=headers, allow_redirects=True, timeout=30)

    # Google Drive virus-scan confirmation
    if response.status_code == 200 and "text/html" in response.headers.get("Content-Type", ""):
        confirm = re.search(r'confirm=([0-9A-Za-z_\-]+)', response.text)
        if confirm:
            response = session.get(f"{direct}&confirm={confirm.group(1)}",
                                   headers=headers, allow_redirects=True, timeout=30)

    if response.status_code != 200:
        print(f"[ERROR] Download thất bại - HTTP {response.status_code}")
        return None

    print(f"[INFO] Download OK - {len(response.content)} bytes")
    return response.content


def resolve_image(value):
    """
    value là URL → download từ URL
    value là tên folder → random pick từ folder đó
    value trống → random folder bất kỳ trong FOLDER_MAP
    Trả về image bytes hoặc None.
    """
    if not value:
        if FOLDER_MAP:
            folder_name = random.choice(list(FOLDER_MAP.keys()))
            print(f"[INFO] Không có folder chỉ định, random: {folder_name}")
            return random_image_from_folder(folder_name)
        return None
    if value.startswith("http"):
        return download_image(value)
    return random_image_from_folder(value)


def upload_photo(image_bytes, published=False):
    """Upload ảnh lên Facebook, trả về photo_id."""
    if not image_bytes:
        return None
    res = requests.post(
        f"https://graph.facebook.com/v19.0/{PAGE_ID}/photos",
        data={"published": "true" if published else "false", "access_token": FB_TOKEN},
        files={"source": ("image.jpg", image_bytes, "image/jpeg")},
        timeout=30,
    )
    result = res.json()
    photo_id = result.get("id")
    if photo_id:
        print(f"[OK] Upload ảnh Facebook: {photo_id}")
    else:
        print(f"[ERROR] Upload ảnh thất bại: {result}")
    return photo_id


def post_to_facebook(caption, row):
    """
    Đăng bài. Tự động detect:
    - Không có ảnh → text thuần
    - 1 ảnh → single image
    - Nhiều ảnh (IMAGE_PATH_2 trở lên) → carousel
    """
    # Thu thập tất cả image values
    image_values = []
    v1 = str(row.get("IMAGE_PATH_1", "") or row.get("IMAGE_PATH", "")).strip()
    if v1:
        image_values.append(v1)
    idx = 2
    while True:
        v = str(row.get(f"IMAGE_PATH_{idx}", "")).strip()
        if not v:
            break
        image_values.append(v)
        idx += 1

    if not image_values:
        # Text thuần
        res = requests.post(
            f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed",
            data={"message": caption, "access_token": FB_TOKEN},
            timeout=30,
        )
        return res.json().get("id")

    # Upload tất cả ảnh
    photo_ids = []
    for val in image_values:
        img = resolve_image(val)
        pid = upload_photo(img, published=False)
        if pid:
            photo_ids.append(pid)

    if not photo_ids:
        print("[WARN] Không upload được ảnh nào, fallback text thuần")
        res = requests.post(
            f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed",
            data={"message": caption, "access_token": FB_TOKEN},
            timeout=30,
        )
        return res.json().get("id")

    data = {"message": caption, "access_token": FB_TOKEN}
    for n, pid in enumerate(photo_ids):
        data[f"attached_media[{n}]"] = json.dumps({"media_fbid": pid})

    res    = requests.post(f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed",
                           data=data, timeout=30)
    result = res.json()
    print(f"[INFO] Kết quả đăng bài: {result}")
    return result.get("id")


def add_comment(post_id, text, image_value):
    """Comment vào bài đăng (text + ảnh tùy chọn)."""
    if not text and not image_value:
        return
    data = {"access_token": FB_TOKEN}
    if text:
        data["message"] = text

    img = resolve_image(image_value) if image_value else None

    if img:
        res = requests.post(
            f"https://graph.facebook.com/v19.0/{post_id}/comments",
            data=data,
            files={"source": ("image.jpg", img, "image/jpeg")},
            timeout=30,
        )
    else:
        res = requests.post(
            f"https://graph.facebook.com/v19.0/{post_id}/comments",
            data=data,
            timeout=30,
        )
    print(f"[INFO] Comment: {res.json()}")


# ── Main ──────────────────────────────────────────────────────────────────────

records = sheet.get_all_records(head=3)
print(f"[INFO] Đọc được {len(records)} dòng từ Sheet")

for i, row in enumerate(records):
    gio_dang = str(row.get("GIỜ ĐĂNG", "")).strip()
    status   = str(row.get("STATUS", "")).strip()

    # Cho phép "Test ngay" để bypass kiểm tra giờ
    if status == "Test ngay":
        pass
    elif gio_dang != current_time or status != "Chưa làm":
        continue

    row_num = i + 4
    caption = str(row.get("CAPTION ĐẦY ĐỦ", "")).strip()
    print(f"\n[INFO] Xử lý dòng {row_num}: {caption[:60]}...")

    post_id = post_to_facebook(caption, row)

    if post_id:
        # 3 comments
        for idx in range(1, 4):
            c_text = str(row.get(f"COMMENT_{idx}", "")).strip() or None
            c_img  = str(row.get(f"COMMENT_{idx}_IMAGE", "")).strip() or None
            if c_text or c_img:
                add_comment(post_id, c_text, c_img)

        # Cập nhật Sheet
        headers = list(row.keys())
        sheet.update_cell(row_num, headers.index("STATUS") + 1, "Đã đăng")
        sheet.update
