"""
image_gen_single.py - AKANO Auto Single Post Generator
Doc Sheet rows "Status anh"="single" va chua dang
-> GPT chon layout (S1/S2/S3/S4) + sinh JSON config
-> compose_slide.py render 1 PNG
-> Upload len Facebook as unpublished photo
-> Cap nhat IMAGE_PATH_1
"""

import os
import json
import subprocess
import tempfile
import gspread
import requests
from pathlib import Path
from google.oauth2.service_account import Credentials

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
FB_TOKEN       = os.environ["FB_PAGE_TOKEN"]
PAGE_ID        = "111199154354113"

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
creds      = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

gs_client   = gspread.authorize(creds)
spreadsheet = gs_client.open_by_key(os.environ["SHEET_ID"])
sheet       = spreadsheet.worksheet("Post")

REPO_ROOT      = Path(__file__).parent
COMPOSE_SCRIPT = REPO_ROOT / "compose_slide.py"

SYSTEM_PROMPT = """
Ban la creative director cho thuong hieu AKANO -- kho si gia dung nhap khau B2B.
Nhiem vu: dua vao tieu de va caption bai dang, chon layout phu hop va sinh JSON config cho 1 slide don.

Brand voice: Nguoi trong nghe noi voi nguoi dang kinh doanh -- thang, thuc chien, khong hoa my.
Audience: chu shop online, seller TMDT, chu kho si, dai ly phan phoi.
Visual: Editorial magazine B2B -- Navy #1A2D5A, Red #ED1C24, White. Headline Title Case Bold.

--- LAYOUT SELECTION RULES ---
S1 Quote Card    -> khi co 1 cau insight co dong manh, viral/share
S2 Insight Card  -> khi la bai viet suy nghi, goc nhin, triet ly kinh doanh (thuan text)
S3 Stat/Milestone -> khi co so lieu lon, milestone, countdown
S4 Tip Card      -> khi la meo, checklist, huong dan thuc chien (co bullet points)

--- OUTPUT JSON SCHEMA ---

S1:
{
  "topic": "<slug>",
  "output_dir": "output/<slug>",
  "caption": "<giu nguyen caption input>",
  "hashtags": ["akano"],
  "slides": [{
    "layout": "S1",
    "content": {
      "quote": "<cau insight chinh 2-8 tu x 1-3 dong, dung \\n xuong dong>",
      "attribution": "— AKANO · Nguồn hàng kinh doanh"
    }
  }]
}

S2:
{
  "topic": "<slug>",
  "output_dir": "output/<slug>",
  "caption": "<giu nguyen caption input>",
  "hashtags": ["akano"],
  "slides": [{
    "layout": "S2",
    "content": {
      "title": "<title 2-3 dong Title Case, dung \\n>",
      "body": ["<doan 1 dat van de>", "<doan 2 phan tich>", "<doan 3 ket luan>"],
      "cta": "Inbox để chia sẻ thêm"
    }
  }]
}

S3:
{
  "topic": "<slug>",
  "output_dir": "output/<slug>",
  "caption": "<giu nguyen caption input>",
  "hashtags": ["akano"],
  "slides": [{
    "layout": "S3",
    "content": {
      "label": "<LABEL 2-3 TU CAPS>",
      "big_number": "<so/con so max 8 ky tu>",
      "caption": "<mo ta ngan 3-6 tu>",
      "subtext": "<cau phu 12-18 tu>"
    }
  }]
}

S4:
{
  "topic": "<slug>",
  "output_dir": "output/<slug>",
  "caption": "<giu nguyen caption input>",
  "hashtags": ["akano"],
  "slides": [{
    "layout": "S4",
    "content": {
      "label": "<LABEL 2-3 TU CAPS>",
      "headline": "<headline 2 dong Title Case, dung \\n>",
      "items": ["<item 1 6-12 tu>", "<item 2>", "<item 3>"],
      "cta": "Inbox để Akano tư vấn"
    }
  }]
}

Quy tac chung:
- Chi tra ve JSON thuan, khong giai thich
- Slug kebab-case khong dau
- Giu nguyen toan bo caption input, khong rut gon
""".strip()


def generate_config(tieu_de, caption):
    user_msg = "Tieu de bai: " + tieu_de + "\n\nCaption:\n" + caption
    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": "Bearer " + OPENAI_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 800,
            "temperature": 0.7,
        },
        timeout=60,
    )
    data = res.json()
    if "choices" not in data:
        print("[ERROR] GPT loi: " + str(data))
        return None
    raw = data["choices"][0]["message"]["content"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print("[ERROR] Parse JSON that bai: " + str(e))
        return None


def render_single(config, tmp_dir):
    config_path = tmp_dir / "single_config.json"
    config["output_dir"] = str(tmp_dir / "slides")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print("[INFO] Chay compose_slide.py...")
    result = subprocess.run(
        ["python", str(COMPOSE_SCRIPT), "--carousel", str(config_path)],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print("[ERROR] compose_slide.py failed:\n" + result.stderr)
        return None
    out_dir = tmp_dir / "slides"
    pngs = list(out_dir.glob("slide_1_*.png"))
    if not pngs:
        pngs = list(out_dir.glob("slide_*.png"))
    if not pngs:
        print("[ERROR] Khong tim thay PNG output")
        return None
    png = pngs[0]
    print("[INFO] Render xong: " + png.name)
    return png


def upload_to_facebook(png_path):
    with open(png_path, "rb") as f:
        res = requests.post(
            "https://graph.facebook.com/v22.0/" + PAGE_ID + "/photos",
            data={"published": "false", "access_token": FB_TOKEN},
            files={"source": ("image.png", f, "image/png")},
            timeout=60,
        )
    result = res.json()
    photo_id = result.get("id")
    if photo_id:
        print("[OK] Upload Facebook photo: " + str(photo_id))
        return "fb:" + str(photo_id)
    print("[ERROR] Upload Facebook that bai: " + str(result))
    return None


records = sheet.get_all_records(head=3)
print("[INFO] Doc duoc " + str(len(records)) + " dong tu Sheet")

for i, row in enumerate(records):
    loai_anh = str(row.get("Status anh", "") or row.get("Status ảnh", "")).strip().lower()
    if loai_anh not in ("single", "singer-post", "single-post"):
        continue

    status = str(row.get("STATUS", "")).strip()
    if status in ("Đã đăng", "Da dang"):
        print("[SKIP] Dong " + str(i + 4) + ": da dang roi, bo qua")
        continue

    row_num = i + 4
    tieu_de = str(row.get("TIÊu ĐỀ BÀI", "") or row.get("TIEU DE BAI", "")).strip()
    caption = str(row.get("CAPTION ĐẦY ĐỦ", "") or row.get("CAPTION DAY DU", "")).strip()
    headers = list(row.keys())

    print("\n[INFO] Xu ly dong " + str(row_num) + ": " + tieu_de[:60])

    if not caption:
        print("[WARN] Caption trong, bo qua")
        continue

    print("[INFO] Goi GPT chon layout + sinh config...")
    config = generate_config(tieu_de or caption[:80], caption)
    if not config:
        print("[ERROR] Dong " + str(row_num) + ": Khong sinh duoc config, bo qua")
        continue

    layout = config.get("slides", [{}])[0].get("layout", "?")
    print("[INFO] Layout GPT chon: " + layout)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        png = render_single(config, tmp_dir)

        if not png:
            print("[ERROR] Dong " + str(row_num) + ": Render that bai")
            continue

        fb_id = upload_to_facebook(png)
        if fb_id and "IMAGE_PATH_1" in headers:
            sheet.update_cell(row_num, headers.index("IMAGE_PATH_1") + 1, fb_id)
            print("[OK] IMAGE_PATH_1 = " + fb_id)

    print("[OK] Dong " + str(row_num) + " da sinh anh xong! Layout: " + layout)

print("\n[INFO] image_gen_single.py hoan tat.")
