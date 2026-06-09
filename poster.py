import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta

# Kết nối Google Sheet
creds_json = os.environ["GOOGLE_CREDENTIALS"]
creds_dict = json.loads(creds_json)
creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
client = gspread.authorize(creds)

sheet_id = os.environ["SHEET_ID"]
sheet = client.open_by_key(sheet_id).worksheet("Post")

FB_TOKEN = os.environ["FB_PAGE_TOKEN"]
PAGE_ID = "111199154354113"

def upload_photo(image_url):
    """Tải ảnh về rồi upload lên FB"""
    img_response = requests.get(image_url, headers={"User-Agent": "Mozilla/5.0"})
    if img_response.status_code != 200:
        print(f"Không tải được ảnh - status: {img_response.status_code}")
        return None
    res = requests.post(
        f"https://graph.facebook.com/v19.0/{PAGE_ID}/photos",
        data={
            "published": "false",
            "access_token": FB_TOKEN
        },
        files={"source": ("image.jpg", img_response.content, "image/jpeg")}
    )
    result = res.json()
    print(f"Upload ảnh: {result}")
    return result.get("id")

def post_with_image(caption, image_url):
    """Đăng bài kèm ảnh"""
    photo_id = upload_photo(image_url)
    if not photo_id:
        print("Upload ảnh thất bại — bỏ qua bài này")
        return None
    res = requests.post(
        f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed",
        data={
            "message": caption,
            "attached_media[0]": json.dumps({"media_fbid": photo_id}),
            "access_token": FB_TOKEN
        }
    )
    return res.json()

def post_text_only(caption):
    """Đăng bài text thuần"""
    res = requests.post(
        f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed",
        data={"message": caption, "access_token": FB_TOKEN}
    )
    return res.json()

def add_comment(post_id, text, image_url=None):
    """Comment text hoặc kèm ảnh"""
    if image_url:
        photo_id = upload_photo(image_url)
        if photo_id:
            res = requests.post(
                f"https://graph.facebook.com/v19.0/{post_id}/comments",
                data={
                    "message": text,
                    "attachment_id": photo_id,
                    "access_token": FB_TOKEN
                }
            )
            print(f"Comment ảnh: {res.json()}")
            return
    res = requests.post(
        f"https://graph.facebook.com/v19.0/{post_id}/comments",
        data={"message": text, "access_token": FB_TOKEN}
    )
    print(f"Comment text: {res.json()}")

# Đọc dữ liệu
rows = sheet.get_all_records(head=3)
vn_tz = timezone(timedelta(hours=7))
now = datetime.now(vn_tz)
current_time = now.strftime("%H:%M")

print(f"Giờ hiện tại (VN): {current_time}")

for i, row in enumerate(rows):
    gio_dang = str(row.get("GIỜ ĐĂNG", "")).strip()
    status = str(row.get("STATUS", "")).strip()
    caption = str(row.get("CAPTION ĐẦY ĐỦ", "")).strip()
    image_path = str(row.get("IMAGE_PATH", "")).strip()
    comment_1 = str(row.get("COMMENT_1", "")).strip()
    comment_1_image = str(row.get("COMMENT_1_IMAGE", "")).strip()

    if gio_dang == current_time and status == "Chưa làm":
        print(f"Đang đăng bài: {row.get('TIÊU ĐỀ BÀI')}")

        if image_path:
            result = post_with_image(caption, image_path)
        else:
            result = post_text_only(caption)

        print(f"Kết quả đăng bài: {result}")

        if result and "id" in result:
            post_id = result["id"]
            sheet.update_cell(i + 4, 11, "Đã đăng")
            sheet.update_cell(i + 4, 12, post_id)
            sheet.update_cell(i + 4, 13, now.strftime("%Y-%m-%d %H:%M"))
            print("Đã cập nhật trạng thái!")

            if comment_1:
                add_comment(post_id, comment_1, comment_1_image if comment_1_image else None)

        break
