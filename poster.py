import os
import json
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# Kết nối Google Sheet
creds_json = os.environ["GOOGLE_CREDENTIALS"]
creds_dict = json.loads(creds_json)
creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
client = gspread.authorize(creds)

sheet_id = os.environ["SHEET_ID"]
sheet = client.open_by_key(sheet_id).worksheet("Post")

FB_TOKEN = os.environ["FB_PAGE_TOKEN"]
PAGE_ID = "111199154354113"

# Đọc dữ liệu
rows = sheet.get_all_records(head=3)
now = datetime.now()
current_time = now.strftime("%H:%M")

print(f"Giờ hiện tại: {current_time}")

for i, row in enumerate(rows):
    gio_dang = str(row.get("GIỜ ĐĂNG", "")).strip()
    status = str(row.get("STATUS", "")).strip()
    caption = str(row.get("CAPTION ĐẦY ĐỦ", "")).strip()

    if gio_dang == current_time and status == "Chưa làm":
        print(f"Đang đăng bài: {row.get('TIÊU ĐỀ BÀI')}")
        res = requests.post(
            f"https://graph.facebook.com/v19.0/{PAGE_ID}/feed",
            data={"message": caption, "access_token": FB_TOKEN}
        )
        result = res.json()
        print(result)

        if "id" in result:
            sheet.update_cell(i + 4, 11, "Đã đăng")
            sheet.update_cell(i + 4, 13, now.strftime("%Y-%m-%d %H:%M"))
            print("Đã cập nhật trạng thái!")
        break
