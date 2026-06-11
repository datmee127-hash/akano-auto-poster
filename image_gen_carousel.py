"""
image_gen_carousel.py - AKANO Auto Carousel Generator
Doc Sheet rows "Status anh"="carousel" va chua dang (STATUS != "Da dang")
-> Goi GPT-4o-mini sinh JSON config
-> Chay compose_slide.py render 4 PNGs
-> Upload len Facebook as unpublished photo (fb:ID)
-> Cap nhat IMAGE_PATH_1..4
poster.py dung fb:ID de dang carousel
"""

import os
import json
import subprocess
import tempfile
import gspread
import requests
from pathlib import Path
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta

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

SYSTEM_PROMPT_SINGLE = """
Ban la creative director cho thuong hieu AKANO -- kho si gia dung nhap khau B2B.
Nhiem vu: dua vao tieu de va caption bai dang, sinh ra JSON config cho tool render 1 slide DUNG (single post).

Brand voice: Nguoi trong nghe noi voi nguoi dang kinh doanh -- thang, thuc chien, khong hoa my.
Audience: chu shop online, seller TMDT, chu kho si, dai ly phan phoi.
Visual: Editorial magazine B2B -- Navy #1A2D5A, Red #ED1C24, White. Headline Title Case Bold.

JSON schema bat buoc (chi 1 slide, layout S2 hoac S4):
{
  "topic": "<slug-khong-dau>",
  "output_dir": "output/<slug>",
  "caption": "<noi dung caption tu input, giu nguyen>",
  "hashtags": ["akano", "nguonhangsi"],
  "slides": [
    {
      "layout": "S2",
      "content": {
        "title": "<tieu de 4-7 tu, Title Case, 2 dong>",
        "body": [
          "<doan 1 -- dat van de 2-3 cau>",
          "<doan 2 -- goc nhin cu the, co so lieu>",
          "<doan 3 -- bai hoc / conclusion>"
        ],
        "cta": "Inbox de duoc tu van nguon hang"
      }
    }
  ]
}

Quy tac:
- Chi sinh 1 slide duy nhat
- Layout S2 neu insight/van de, layout S4 neu checklist/meo
- S4 schema: {"label": "...", "headline": "...", "items": ["...", "...", "..."], "cta": "..."}
- Headline Title Case, khong CAPS toan bo
- Chi tra ve JSON thuan, khong giai thich them
""".strip()

SYSTEM_PROMPT = """
Ban la creative director cho thuong hieu AKANO -- kho si gia dung nhap khau B2B.
Nhiem vu: dua vao tieu de va caption bai dang, sinh ra JSON config cho tool render carousel 4 slide.

Brand voice: Nguoi trong nghe noi voi nguoi dang kinh doanh -- thang, thuc chien, khong hoa my.
Audience: chu shop online, seller TMDT, chu kho si, dai ly phan phoi.
Visual: Editorial magazine B2B -- Navy #1A2D5A, Red #ED1C24, White. Headline Title Case Bold.

JSON schema bat buoc:
{
  "topic": "<slug-khong-dau>",
  "output_dir": "output/<slug>",
  "caption": "<noi dung caption tu input, giu nguyen>",
  "hashtags": ["akano", "nguonhangsi"],
  "slides": [
    {
      "layout": "L1",
      "content": {
        "headline": "<tieu de lon 2-3 dong>",
        "sub_hook": "<cau phu 1-2 dong>",
        "body": ["<diem 1>", "<diem 2>", "<diem 3>"]
      }
    },
    {
      "layout": "L2",
      "content": {
        "headline": "<tieu de slide 2>",
        "items": ["<muc 1>", "<muc 2>", "<muc 3>"]
      }
    },
    {
      "layout": "L3",
      "content": {
        "headline": "<tieu de slide 3>",
        "cards": [
          {"title": "<ten ngan>", "body": "<giai thich ngan>"},
          {"title": "<ten ngan>", "body": "<giai thich ngan>", "highlight": true},
          {"title": "<ten ngan>", "body": "<giai thich ngan>"},
          {"title": "<ten ngan>", "body": "<giai thich ngan>"}
        ]
      }
    },
    {
      "layout": "L5",
      "content": {
        "headline": "<CTA headline 2-3 dong>",
        "subtext": "<cau ket 1-2 dong>",
        "cta": "Inbox để nhận tư vấn nguồn hàng",
        "footer": "AKANO - NGUỒN HÀNG KINH DOANH - akano.vn - 0988.198.158"
      }
    }
  ]
}

Quy tac:
- Slide 1 (L1): Hook manh, gay to mo, dung pain point
- Slide 2 (L2): Liet ke van de / ly do (3 items)
- Slide 3 (L3): Phan tich qua 4 cards
- Slide 4 (L5): CTA ro, keu goi inbox
- Headline Title Case, khong CAPS toan bo
- Chi tra ve JSON thuan, khong giai thich them
""".strip()


def generate_config(tieu_de, caption, is_single=False):
    user_msg = "Tieu de bai: " + tieu_de + "\n\nCaption:\n" + caption
    prompt   = SYSTEM_PROMPT_SINGLE if is_single else SYSTEM_PROMPT
    max_tok  = 600 if is_single else 1200
    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": "Bearer " + OPENAI_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": max_tok,
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


def render_carousel(config, tmp_dir):
    config_path = tmp_dir / "carousel_config.json"
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
        return []
    out_dir = tmp_dir / "slides"
    pngs = sorted(out_dir.glob("slide_*.png"))
    print("[INFO] Render xong: " + str([p.name for p in pngs]))
    return pngs


def upload_to_facebook(png_path):
    """Upload anh len Facebook as unpublished photo, tra ve 'fb:PHOTO_ID'."""
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

vn_tz        = timezone(timedelta(hours=7))
current_time = datetime.now(vn_tz).strftime("%H:%M")
print("[INFO] Gio Viet Nam: " + current_time)

for i, row in enumerate(records):
    loai_anh = str(row.get("FORMAT", "") or row.get("Status anh", "") or row.get("Status ảnh", "")).strip().lower()
    if loai_anh not in ("carousel", "single", "singer-post", "single-post"):
        continue

    status   = str(row.get("STATUS", "")).strip()
    gio_dang = str(row.get("GIỜ ĐĂNG", "") or row.get("GIO DANG", "")).strip()

    if status in ("Đã đăng", "Da dang"):
        continue

    if status == "Test ngay":
        pass
    elif gio_dang != current_time or status not in ("Chua lam", "Chưa làm"):
        continue

    row_num = i + 4
    tieu_de = str(row.get("TIÊu ĐỀ BÀI", "") or row.get("TIEU DE BAI", "")).strip()
    caption = str(row.get("CAPTION ĐẦY ĐỦ", "") or row.get("CAPTION DAY DU", "")).strip()
    headers = list(row.keys())

    print("\n[INFO] Xu ly dong " + str(row_num) + ": " + tieu_de[:60])

    if not caption:
        print("[WARN] Caption trong, bo qua")
        continue

    is_single = loai_anh in ("single", "singer-post", "single-post")
    print("[INFO] Goi GPT sinh JSON config (loai: " + ("single" if is_single else "carousel") + ")...")
    config = generate_config(tieu_de or caption[:80], caption, is_single=is_single)
    if not config:
        print("[ERROR] Dong " + str(row_num) + ": Khong sinh duoc config, bo qua")
        continue

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pngs = render_carousel(config, tmp_dir)

        if not pngs:
            print("[ERROR] Dong " + str(row_num) + ": Render that bai")
            continue

        img_cols = ["IMAGE_PATH_1", "IMAGE_PATH_2", "IMAGE_PATH_3", "IMAGE_PATH_4"]
        # Single post: chi upload 1 anh dau
        upload_pngs = pngs[:1] if is_single else pngs[:4]

        for idx, png_path in enumerate(upload_pngs):
            col_name = img_cols[idx]
            fb_id = upload_to_facebook(png_path)
            if fb_id and col_name in headers:
                sheet.update_cell(row_num, headers.index(col_name) + 1, fb_id)
                print("[OK] " + col_name + " = " + fb_id)

    print("[OK] Dong " + str(row_num) + " da sinh anh xong!")

print("\n[INFO] image_gen_carousel.py hoan tat.")
