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
print(f"[INFO] Gio Viet Nam hien tai: {current_time}")

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

# ── Load folder map tu tab FOLDERS ────────────────────────────────────────────

def load_folder_map():
    try:
        folders_sheet = spreadsheet.worksheet("FOLDERS")
        records = folders_sheet.get_all_records()
        return {str(r.get("TEN", "") or r.get("TÊN", "")).strip().lower(): str(r.get("FOLDER_ID", "")).strip()
                for r in records if r.get("FOLDER_ID")}
    except Exception as e:
        print("[WARN] Khong doc duoc tab FOLDERS: " + str(e))
        return {}

FOLDER_MAP = load_folder_map()
print("[INFO] Folder map: " + str(FOLDER_MAP))

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_direct_url(url):
    """Convert Google Drive share link -> direct download URL."""
    if url and "drive.google.com" in url:
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if match:
            return "https://drive.google.com/uc?export=download&id=" + match.group(1)
    return url


def random_image_from_folder(folder_name):
    """List anh trong Drive folder -> random pick 1 -> tra ve bytes."""
    key       = folder_name.strip().lower()
    folder_id = FOLDER_MAP.get(key)
    if not folder_id:
        print("[ERROR] Khong tim thay folder '" + folder_name + "' trong FOLDERS tab")
        return None

    result = drive.files().list(
        q="'" + folder_id + "' in parents and mimeType contains 'image/' and trashed=false",
        fields="files(id, name)",
        pageSize=100,
    ).execute()

    files = result.get("files", [])
    if not files:
        print("[ERROR] Folder '" + folder_name + "' khong co anh")
        return None

    chosen = random.choice(files)
    print("[INFO] Random pick tu '" + folder_name + "': " + chosen["name"])

    file_bytes = drive.files().get_media(fileId=chosen["id"]).execute()
    return file_bytes


def download_image(url):
    """Download anh tu URL (ho tro Google Drive share link)."""
    direct = get_direct_url(url)
    print("[INFO] Download anh: " + direct)

    session  = requests.Session()
    headers  = {"User-Agent": "Mozilla/5.0"}
    response = session.get(direct, headers=headers, allow_redirects=True, timeout=30)

    # Google Drive virus-scan confirmation
    if response.status_code == 200 and "text/html" in response.headers.get("Content-Type", ""):
        confirm = re.search(r'confirm=([0-9A-Za-z_\-]+)', response.text)
        if confirm:
            response = session.get(direct + "&confirm=" + confirm.group(1),
                                   headers=headers, allow_redirects=True, timeout=30)

    if response.status_code != 200:
        print("[ERROR] Download that bai - HTTP " + str(response.status_code))
        return None

    print("[INFO] Download OK - " + str(len(response.content)) + " bytes")
    return response.content


def resolve_image(value):
    """
    value la URL -> download tu URL
    value la ten folder -> random pick tu folder do
    value trong -> random folder bat ky trong FOLDER_MAP
    Tra ve image bytes hoac None.
    """
    if not value:
        if FOLDER_MAP:
            folder_name = random.choice(list(FOLDER_MAP.keys()))
            print("[INFO] Khong co folder chi dinh, random: " + folder_name)
            return random_image_from_folder(folder_name)
        return None
    if value.startswith("http"):
        return download_image(value)
    return random_image_from_folder(value)


def upload_photo(image_bytes, published=False):
    """Upload anh len Facebook, tra ve photo_id."""
    if not image_bytes:
        return None
    res = requests.post(
        "https://graph.facebook.com/v22.0/" + PAGE_ID + "/photos",
        data={"published": "true" if published else "false", "access_token": FB_TOKEN},
        files={"source": ("image.jpg", image_bytes, "image/jpeg")},
        timeout=30,
    )
    result = res.json()
    photo_id = result.get("id")
    if photo_id:
        print("[OK] Upload anh Facebook: " + str(photo_id))
    else:
        print("[ERROR] Upload anh that bai: " + str(result))
    return photo_id


def post_to_facebook(caption, row):
    """
    Dang bai. Tu dong detect:
    - Khong co anh -> text thuan
    - 1 anh -> single image
    - Nhieu anh (IMAGE_PATH_2 tro len) -> carousel
    """
    # Thu thap tat ca image values
    image_values = []
    v1 = str(row.get("IMAGE_PATH_1", "") or row.get("IMAGE_PATH", "")).strip()
    if v1:
        image_values.append(v1)
    idx = 2
    while True:
        v = str(row.get("IMAGE_PATH_" + str(idx), "")).strip()
        if not v:
            break
        image_values.append(v)
        idx += 1

    if not image_values:
        # Text thuan
        res = requests.post(
            "https://graph.facebook.com/v22.0/" + PAGE_ID + "/feed",
            data={"message": caption, "access_token": FB_TOKEN},
            timeout=30,
        )
        return res.json().get("id")

    # Upload tat ca anh
    photo_ids = []
    for val in image_values:
        # Neu la fb:PHOTO_ID (da pre-upload boi image_gen_carousel.py) -> dung luon
        if val.startswith("fb:"):
            photo_ids.append(val[3:])
            print("[INFO] Dung pre-uploaded photo: " + val[3:])
        else:
            img = resolve_image(val)
            pid = upload_photo(img, published=False)
            if pid:
                photo_ids.append(pid)

    if not photo_ids:
        print("[WARN] Khong upload duoc anh nao, fallback text thuan")
        res = requests.post(
            "https://graph.facebook.com/v22.0/" + PAGE_ID + "/feed",
            data={"message": caption, "access_token": FB_TOKEN},
            timeout=30,
        )
        return res.json().get("id")

    # Dung multipart/form-data de brackets [0],[1]... khong bi URL-encode thanh %5B%5D
    fields = [
        ("message",      (None, caption)),
        ("access_token", (None, FB_TOKEN)),
    ]
    for n, pid in enumerate(photo_ids):
        fields.append(("attached_media[" + str(n) + "]", (None, json.dumps({"media_fbid": pid}))))

    res    = requests.post("https://graph.facebook.com/v22.0/" + PAGE_ID + "/feed",
                           files=fields, timeout=30)
    result = res.json()
    print("[INFO] Ket qua dang bai: " + str(result))
    return result.get("id")


def add_comment(post_id, text, image_value):
    """Comment vao bai dang (text + anh tuy chon). Neu khong co anh chi dinh, tu dong random anh tu folder."""
    data = {"access_token": FB_TOKEN}
    if text:
        data["message"] = text

    img = resolve_image(image_value)

    if img:
        res = requests.post(
            "https://graph.facebook.com/v22.0/" + post_id + "/comments",
            data=data,
            files={"source": ("image.jpg", img, "image/jpeg")},
            timeout=30,
        )
    else:
        res = requests.post(
            "https://graph.facebook.com/v22.0/" + post_id + "/comments",
            data=data,
            timeout=30,
        )
    print("[INFO] Comment: " + str(res.json()))


# ── Main ──────────────────────────────────────────────────────────────────────

records = sheet.get_all_records(head=3)
print("[INFO] Doc duoc " + str(len(records)) + " dong tu Sheet")

for i, row in enumerate(records):
    gio_dang = str(row.get("GIO DANG", "") or row.get("GIỜ ĐĂNG", "")).strip()
    status   = str(row.get("STATUS", "")).strip()

    # Cho phep "Test ngay" de bypass kiem tra gio
    if status == "Test ngay":
        pass
    elif gio_dang != current_time or status != "Chua lam" and status != "Chưa làm":
        continue

    row_num = i + 4
    caption = str(row.get("CAPTION DAY DU", "") or row.get("CAPTION ĐẦY ĐỦ", "")).strip()
    print("\n[INFO] Xu ly dong " + str(row_num) + ": " + caption[:60] + "...")

    post_id = post_to_facebook(caption, row)

    if post_id:
        # 3 comments
        for idx in range(1, 4):
            c_text = str(row.get("COMMENT_" + str(idx), "")).strip() or None
            c_img  = str(row.get("COMMENT_" + str(idx) + "_IMAGE", "")).strip() or None
            add_comment(post_id, c_text, c_img)

        # Cap nhat Sheet
        headers = list(row.keys())
        sheet.update_cell(row_num, headers.index("STATUS") + 1, "Đã đăng")
        sheet.update_cell(row_num, headers.index("FACEBOOK_POST_ID") + 1, post_id)
        sheet.update_cell(row_num, headers.index("POSTED_AT") + 1,
                          now.strftime("%Y-%m-%d %H:%M"))
        print("[OK] Dang thanh cong! Post ID: " + post_id)
    else:
        print("[ERROR] Dang that bai dong " + str(row_num))
