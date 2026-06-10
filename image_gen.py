"""
image_gen.py - AKANO Auto Image Generator (unified)
"""

import os
import json
import subprocess
import tempfile
import gspread
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
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

CAROUSEL_PROMPT = """Ban la creative director AKANO -- kho si gia dung nhap khau B2B.
Sinh JSON config carousel 4 slide. Brand: Navy #1A2D5A, Red #ED1C24. Headline Title Case.

Tra ve JSON theo dung schema nay, khong them gi khac:
{
  "topic": "slug-kebab-case",
  "output_dir": "output/slug",
  "caption": "(giu nguyen caption input)",
  "hashtags": ["akano", "nguonhangsi"],
  "slides": [
    {"layout": "L1", "content": {"headline": "Tieu De Chinh\\n2-3 Dong", "sub_hook": "Cau phu 1-2 dong", "body": ["Diem 1", "Diem 2", "Diem 3"]}},
    {"layout": "L2", "content": {"headline": "Tieu De Slide 2", "items": ["Muc 1", "Muc 2", "Muc 3"]}},
    {"layout": "L3", "content": {"headline": "Tieu De Slide 3", "cards": [
      {"title": "Ten 1", "body": "Mo ta 1"},
      {"title": "Ten 2", "body": "Mo ta 2", "highlight": true},
      {"title": "Ten 3", "body": "Mo ta 3"},
      {"title": "Ten 4", "body": "Mo ta 4"}
    ]}},
    {"layout": "L5", "content": {
      "headline": "CTA Headline\\n2-3 Dong",
      "subtext": "Cau ket 1-2 dong",
      "cta": "Inbox để nhận tư vấn nguồn hàng",
      "footer": "AKANO - NGUỒN HÀNG KINH DOANH - akano.vn - 0988.198.158"
    }}
  ]
}
Chi tra JSON thuan, khong giai thich."""

SINGLE_PROMPT = """Ban la creative director AKANO -- kho si gia dung nhap khau B2B.
Chon layout va sinh JSON config cho 1 slide don. Headline Title Case.

Quy tac chon layout:
- S1: co 1 cau insight manh, co dong, viral
- S2: bai viet suy nghi, triet ly, thuan text
- S3: co so lieu / milestone / countdown
- S4: meo thuc chien, checklist co bullet

Tra ve JSON theo dung 1 trong 4 schema, khong them gi khac:

S1 (Quote):
{"topic":"slug","output_dir":"output/slug","caption":"(giu nguyen)","hashtags":["akano"],"slides":[{"layout":"S1","content":{"quote":"Cau quote manh\\n1-2 dong nua neu can","attribution":"— AKANO · Nguồn hàng kinh doanh"}}]}

S2 (Insight text):
{"topic":"slug","output_dir":"output/slug","caption":"(giu nguyen)","hashtags":["akano"],"slides":[{"layout":"S2","content":{"title":"Title 2-3 Dong\\nTitle Case","body":["Doan 1 dat van de.","Doan 2 phan tich co so lieu.","Doan 3 ket luan manh."],"cta":"Inbox để chia sẻ thêm"}}]}

S3 (Milestone/Stat):
{"topic":"slug","output_dir":"output/slug","caption":"(giu nguyen)","hashtags":["akano"],"slides":[{"layout":"S3","content":{"label":"LABEL CAPS","big_number":"300+","caption":"Mo ta ngan","subtext":"Cau giai thich 12-18 tu."}}]}

S4 (Tip/Checklist):
{"topic":"slug","output_dir":"output/slug","caption":"(giu nguyen)","hashtags":["akano"],"slides":[{"layout":"S4","content":{"label":"MEO KINH DOANH","headline":"Tieu De\\n2 Dong","items":["Item 1 ro rang","Item 2 thuc te","Item 3 ap dung ngay"],"cta":"Inbox để Akano tư vấn"}}]}

Chi tra JSON thuan, khong giai thich."""


def call_gpt(system_prompt, tieu_de, caption):
    user_msg = "Tieu de bai: " + tieu_de + "\n\nCaption day du:\n" + caption
    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer " + OPENAI_API_KEY, "Content-Type": "application/json"},
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ],
            "max_tokens": 1200,
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
        print("[DEBUG] GPT raw output: " + raw[:300])
        return None


def render(config, tmp_dir):
    config_path = tmp_dir / "config.json"
    config["output_dir"] = str(tmp_dir / "slides")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    result = subprocess.run(
        ["python", str(COMPOSE_SCRIPT), "--carousel", str(config_path)],
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print("[ERROR] compose_slide.py failed:\n" + result.stderr)
        return []
    return sorted((tmp_dir / "slides").glob("slide_*.png"))


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
        print("[OK] Upload FB photo: " + str(photo_id))
        return "fb:" + str(photo_id)
    print("[ERROR] Upload that bai: " + str(result))
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

vn_tz        = timezone(timedelta(hours=7))
current_time = datetime.now(vn_tz).strftime("%H:%M")
print("[INFO] Gio Viet Nam: " + current_time)

records = sheet.get_all_records(head=3)
print("[INFO] Doc duoc " + str(len(records)) + " dong tu Sheet")
if records:
    print("[DEBUG] Headers: " + str(list(records[0].keys())))

for i, row in enumerate(records):
    status   = str(row.get("STATUS", "")).strip()
    loai_anh = str(row.get("Status anh", "") or row.get("Status anh", "")).strip().lower()
    gio_dang = str(row.get("GIO DANG", "") or row.get("GIỜ ĐĂNG", "")).strip()
    row_num  = i + 4
    headers  = list(row.keys())

    if status in ("Da dang", "Đã đăng"):
        continue

    if loai_anh not in ("carousel", "single", "singer-post", "single-post"):
        continue

    if status != "Test ngay":
        if gio_dang != current_time:
            continue
        if status not in ("Chua lam", "Chưa làm"):
            continue

    # Doc tieu de va caption tu nhieu ten cot co the
    tieu_de = ""
    for key in headers:
        if "tieu" in key.lower() and "de" in key.lower():
            val = str(row.get(key, "")).strip()
            if val:
                tieu_de = val
                break

    caption = ""
    for key in headers:
        if "caption" in key.lower():
            val = str(row.get(key, "")).strip()
            if val and len(val) > len(caption):
                caption = val

    print("\n[INFO] Dong " + str(row_num) + " | Loai: " + loai_anh + " | " + tieu_de[:50])
    print("[DEBUG] caption length: " + str(len(caption)) + " | tieu_de: " + repr(tieu_de[:30]))

    if not caption:
        print("[WARN] Caption trong, bo qua")
        continue

    is_carousel   = (loai_anh == "carousel")
    system_prompt = CAROUSEL_PROMPT if is_carousel else SINGLE_PROMPT

    print("[INFO] Goi GPT...")
    config = call_gpt(system_prompt, tieu_de or caption[:80], caption)
    if not config:
        print("[ERROR] Khong sinh duoc config, bo qua")
        continue

    slides = config.get("slides", [])
    if not slides:
        print("[ERROR] GPT tra ve config khong co slides, bo qua")
        continue

    layout = slides[0].get("layout", "?")
    print("[INFO] Layout: " + layout)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pngs = render(config, tmp_dir)

        if not pngs:
            print("[ERROR] Render that bai")
            continue

        if is_carousel:
            img_cols = ["IMAGE_PATH_1", "IMAGE_PATH_2", "IMAGE_PATH_3", "IMAGE_PATH_4"]
            for idx, png_path in enumerate(pngs[:4]):
                col = img_cols[idx]
                fb_id = upload_to_facebook(png_path)
                if fb_id and col in headers:
                    sheet.update_cell(row_num, headers.index(col) + 1, fb_id)
                    print("[OK] " + col + " = " + fb_id)
        else:
            fb_id = upload_to_facebook(pngs[0])
            if fb_id and "IMAGE_PATH_1" in headers:
                sheet.update_cell(row_num, headers.index("IMAGE_PATH_1") + 1, fb_id)
                print("[OK] IMAGE_PATH_1 = " + fb_id)

    print("[OK] Dong " + str(row_num) + " xong!")

print("\n[INFO] image_gen.py hoan tat.")
