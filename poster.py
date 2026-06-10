import os
import re
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta
 
FB_TOKEN = os.environ["FB_PAGE_TOKEN"]
PAGE_ID = "111199154354113"
 
# Vietnam timezone (UTC+7)
vn_tz = timezone(timedelta(hours=7))
now = datetime.now(vn_tz)
current_time = now.strftime("%H:%M")
print(f"[INFO] Giờ Việt Nam hiện tại: {current_time}")
 
 
def get_direct_image_url(url):
    """
    Nếu là link Google Drive share → convert sang link download trực tiếp.
    Ví dụ:
      Input:  https://drive.google.com/file/d/1VrVghz.../view?usp=sharing
      Output: https://drive.google.com/uc?export=download&id=1VrVghz...
    """
    if not url:
        return url
    if "drive.google.com" in url:
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url
 
 
def download_image(url):
    """
    Tải ảnh từ URL về dạng binary.
    Tự động xử lý Google Drive, bao gồm cả cảnh báo virus scan của Drive (file lớn).
    Trả về bytes hoặc None nếu thất bại.
    """
    direct_url = get_direct_image_url(url)
    print(f"[INFO] Đang tải ảnh từ: {direct_url}")
 
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
 
    response = session.get(direct_url, headers=headers, allow_redirects=True, timeout=30)
 
    # Google Drive hiện trang cảnh báo virus scan cho file lớn
    # Phát hiện qua Content-Type là text/html thay vì image/*
    content_type = response.headers.get("Content-Type", "")
    if response.status_code == 200 and "text/html" in content_type:
        print("[INFO] Drive trả về trang xác nhận, đang xử lý...")
        # Tìm confirm token trong HTML
        confirm_match = re.search(r'confirm=([0-9A-Za-z_\-]+)', response.text)
        if confirm_match:
            confirm_token = confirm_match.group(1)
            response = session.get(
                f"{direct_url}&confirm={confirm_token}",
                headers=headers,
                allow_redirects=True,
                timeout=30
            )
        else:
            print("[ERROR] Không tìm được confirm token trong trang Drive")
            return None
 
    if response.status_code != 200:
        print(f"[ERROR] Không tải được ảnh - HTTP status: {response.status_code}")
        return None
 
    print(f"[INFO] Tải ảnh thành công - {len(response.content)} bytes")
    return response.content
 
 
def upload_photo(image_url, published=False):
    """
    Upload ảnh lên Facebook (unpublished hoặc published).
    Trả về photo_id hoặc None nếu thất bại.
    """
    image_bytes = download_image(image_url)
    if not image_bytes:
        return None
 
    res = requests.post(
        f"https://graph.facebook.com/v19.0/{PAGE_ID}/photos",
        data={
            "published": "true" if published else "false",
            "access_token": FB_TOKEN
        },
        files={"source": ("image.jpg", image_bytes, "image/jpeg")},
        timeout=30
    )
    result = res.json()
    print(f"[INFO] Upload ảnh Facebook: {result}")
 
    if "id" in result:
        return result["id"]
    else:
        print(f"[ERROR] Upload ảnh thất bại: {result}")
        return None
 
 
def post_to_facebook(caption, image_url=None):
    """
    Đăng bài lên Facebook fanpage.
    - Nếu có ảnh: upload ảnh trước rồi đăng kèm ảnh
    - Nếu không có ảnh: đăng text thuần
    Trả về post_id hoặc None.
    """
    if image_url:
        photo_id = upload_photo(image_url, published=False)
        if photo_id:
            res = requests.post(
                f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed",
                data={
                    "message": caption,
                    "attached_media[0]": json.dumps({"media_fbid": photo_id}),
                    "access_token": FB_TOKEN
                },
                timeout=30
            )
        else:
            print("[WARN] Không upload được ảnh, fallback đăng text thuần")
            res = requests.post(
                f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed",
                data={"message": caption, "access_token": FB_TOKEN},
                timeout=30
            )
    else:
        res = requests.post(
            f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed",
            data={"message": caption, "access_token": FB_TOKEN},
            timeout=30
        )
 
    result = res.json()
    print(f"[INFO] Kết quả đăng bài: {result}")
    return result.get("id")
 
 
def add_comment(post_id, comment_text, comment_image_url=None):
    """
    Comment vào bài đăng.
    - Nếu có ảnh: upload ảnh rồi comment kèm ảnh
    - Nếu không có ảnh: comment text thuần
    """
    if not comment_text and not comment_image_url:
        return
 
    data = {"access_token": FB_TOKEN}
    if comment_text:
        data["message"] = comment_text
 
    if comment_image_url:
        # Comment với ảnh: dùng endpoint /comments với attachment_url
        # Hoặc upload ảnh trước
        image_bytes = download_image(comment_image_url)
        if image_bytes:
            res = requests.post(
                f"https://graph.facebook.com/v19.0/{post_id}/comments",
                data=data,
                files={"source": ("image.jpg", image_bytes, "image/jpeg")},
                timeout=30
            )
        else:
            print("[WARN] Không tải được ảnh comment, fallback comment text thuần")
            res = requests.post(
                f"https://graph.facebook.com/v19.0/{post_id}/comments",
                data=data,
                timeout=30
            )
    else:
        res = requests.post(
            f"https://graph.facebook.com/v19.0/{post_id}/comments",
            data=data,
            timeout=30
        )
 
    result = res.json()
    print(f"[INFO] Kết quả comment: {result}")
 
 
# ── Kết nối Google Sheet ──────────────────────────────────────────────────────
 
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.environ["GOOGLE_CREDENTIALS"]
creds_dict = json.loads(creds_json)
creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
client = gspread.authorize(creds)
 
SHEET_ID = os.environ["SHEET_ID"]
spreadsheet = client.open_by_key(SHEET_ID)
sheet = spreadsheet.worksheet("Post")
 
# Header ở row 3, data bắt đầu từ row 4
records = sheet.get_all_records(head=3)
print(f"[INFO] Đọc được {len(records)} dòng dữ liệu từ Sheet")
 
# ── Duyệt từng dòng ───────────────────────────────────────────────────────────
 
for i, row in enumerate(records):
    gio_dang = str(row.get("GIỜ ĐĂNG", "")).strip()
    status = str(row.get("STATUS", "")).strip()
 
    if gio_dang != current_time or status != "Chưa làm":
        continue
 
    print(f"[INFO] Xử lý dòng {i+4}: giờ={gio_dang}, status={status}")
 
    caption = str(row.get("CAPTION ĐẦY ĐỦ", "")).strip()
    image_url = str(row.get("IMAGE_PATH", "")).strip() or None
    comment_text = str(row.get("COMMENT_1", "")).strip() or None
    comment_image = str(row.get("COMMENT_1_IMAGE", "")).strip() or None
 
    # Đăng bài
    post_id = post_to_facebook(caption, image_url)
 
    if post_id:
        # Comment (nếu có)
        if comment_text or comment_image:
            add_comment(post_id, comment_text, comment_image)
 
        # Cập nhật Sheet
        col_status = list(row.keys()).index("STATUS") + 1
        col_post_id = list(row.keys()).index("FACEBOOK_POST_ID") + 1
        col_posted_at = list(row.keys()).index("POSTED_AT") + 1
 
        sheet.update_cell(i + 4, col_status, "Đã đăng")
        sheet.update_cell(i + 4, col_post_id, post_id)
        sheet.update_cell(i + 4, col_posted_at, now.strftime("%Y-%m-%d %H:%M"))
        print(f"[OK] Đã đăng thành công! Post ID: {post_id}")
    else:
        print(f"[ERROR] Đăng thất bại cho dòng {i+4}")
