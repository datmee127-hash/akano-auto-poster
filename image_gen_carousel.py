"""
image_gen_carousel.py - AKANO Post Generator
Xu ly: FORMAT = "carousel" | "single" | "single-post" | "singer-post"
- carousel  -> GPT sinh 4 slides JSON -> render 4 PNG -> upload -> IMAGE_PATH_1..4
- single    -> GPT chon layout (S1/S2/S3/S4) + sinh 1 slide JSON -> render 1 PNG -> upload -> IMAGE_PATH_1
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

# ── Prompts ───────────────────────────────────────────────────────────────────

CAROUSEL_PROMPT = """
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

SINGLE_PROMPT = """
Ban la creative director cho thuong hieu AKANO -- kho si gia dung nhap khau B2B.
Nhiem vu: dua vao tieu de va caption bai dang, chon layout phu hop va sinh JSON config cho 1 slide don.

Brand voice: Nguoi trong nghe noi voi nguoi dang kinh doanh -- thang, thuc chien, khong hoa my.
Audience: chu shop online, seller TMDT, chu kho si, dai ly phan phoi.
Visual: Editorial magazine B2B -- Navy #1A2D5A, Red #ED1C24, White. Headline Title Case Bold.

LAYOUT SELECTION RULES:
S1 Quote Card    -> khi co 1 cau insight co dong manh, viral/share
S2 Insight Card  -> khi la bai viet suy nghi, goc nhin, triet ly kinh doanh (thuan text)
S3 Stat/Milestone -> khi co so lieu lon, milestone, countdown
S4 Tip Card      -> khi la meo, checklist, huong dan thuc chien (co bullet points)

OUTPUT JSON SCHEMA (chi 1 slide):

S1: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],"slides":[{"layout":"S1","content":{"quote":"<insight 2-8 tu x 1-3 dong, dung \\n>","attribution":"— AKANO · Nguồn hàng kinh doanh"}}]}

S2: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],"slides":[{"layout":"S2","content":{"title":"<2-3 dong Title Case, dung \\n>","body":["<doan 1>","<doan 2>","<doan 3>"],"cta":"Inbox để chia sẻ thêm"}}]}

S3: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],"slides":[{"layout":"S3","content":{"label":"<LABEL CAPS>","big_number":"<max 8 ky tu>","caption":"<3-6 tu>","subtext":"<12-18 tu>"}}]}

S4: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],"slides":[{"layout":"S4","content":{"label":"<LABEL CAPS>","headline":"<2 dong Title Case, dung \\n>","items":["<item 1>","<item 2>","<item 3>"],"cta":"Inbox để Akano tư vấn"}}]}

Quy tac chung:
- Chi tra ve JSON thuan, khong giai thich
- Slug kebab-case khong dau
- Giu nguyen toan bo caption input
""".strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_config(tieu_de, caption, system_prompt, max_tokens=1200):
    user_msg = "Tieu de bai: " + tieu_de + "\n\nCaption:\n" + caption
    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer " + OPENAI_API_KEY, "Content-Type": "application/json"},
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ],
            "max_tokens": max_tokens,
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


def render_slides(config, tmp_dir):
    config_path = tmp_dir / "config.json"
    config["output_dir"] = str(tmp_dir / "slides")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print("[INFO] Chay compose_slide.py...")
    result = subprocess.run(
        ["python", str(COMPOSE_SCRIPT), "--carousel", str(config_path)],
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print("[ERROR] compose_slide.py failed:\n" + result.stderr)
        return []
    pngs = sorted((tmp_dir / "slides").glob("slide_*.png"))
    print("[INFO] Render xong: " + str([p.name for p in pngs]))
    return pngs


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


# ── Main ──────────────────────────────────────────────────────────────────────

SINGLE_FORMATS   = ("single", "single-post", "singer-post")
CAROUSEL_FORMATS = ("carousel",)

records = sheet.get_all_records(head=3)

# DEBUG: tong hop FORMAT x STATUS de chuan doan
if records:
    print("[DEBUG] Column headers: " + str(list(records[0].keys())))
    fmt_sta = {}
    for r in records:
        fmt = str(r.get("FORMAT","")).strip()
        sta = str(r.get("STATUS","")).strip()
        k = fmt + " | " + sta
        fmt_sta[k] = fmt_sta.get(k, 0) + 1
    for k, v in sorted(fmt_sta.items()):
        if k.strip(" |"):
            print("[DEBUG] " + k + " => " + str(v) + " rows")

print("[INFO] Doc duoc " + str(len(records)) + " dong tu Sheet")

vn_tz        = timezone(timedelta(hours=7))
current_time = datetime.now(vn_tz).strftime("%H:%M")
print("[INFO] Gio Viet Nam: " + current_time)

for i, row in enumerate(records):
    loai_anh = str(row.get("FORMAT", "") or row.get("Status anh", "") or row.get("Status ảnh", "")).strip().lower()

    is_carousel = loai_anh in CAROUSEL_FORMATS
    is_single   = loai_anh in SINGLE_FORMATS
    if not is_carousel and not is_single:
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

    if not caption:
        print("[WARN] Dong " + str(row_num) + ": Caption trong, bo qua")
        continue

    # ── CAROUSEL ──────────────────────────────────────────────────────────────
    if is_carousel:
        print("\n[INFO] [CAROUSEL] Dong " + str(row_num) + ": " + tieu_de[:60])
        config = generate_config(tieu_de or caption[:80], caption, CAROUSEL_PROMPT, max_tokens=1200)
        if not config:
            print("[ERROR] Dong " + str(row_num) + ": Khong sinh duoc config")
            continue

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            pngs = render_slides(config, tmp_dir)
            if not pngs:
                print("[ERROR] Dong " + str(row_num) + ": Render that bai")
                continue

            img_cols = ["IMAGE_PATH_1", "IMAGE_PATH_2", "IMAGE_PATH_3", "IMAGE_PATH_4"]
            for idx, png_path in enumerate(pngs[:4]):
                col_name = img_cols[idx]
                fb_id = upload_to_facebook(png_path)
                if fb_id and col_name in headers:
                    sheet.update_cell(row_num, headers.index(col_name) + 1, fb_id)
                    print("[OK] " + col_name + " = " + fb_id)

        print("[OK] Dong " + str(row_num) + " carousel xong!")

    # ── SINGLE ────────────────────────────────────────────────────────────────
    elif is_single:
        print("\n[INFO] [SINGLE] Dong " + str(row_num) + ": " + tieu_de[:60])
        config = generate_config(tieu_de or caption[:80], caption, SINGLE_PROMPT, max_tokens=800)
        if not config:
            print("[ERROR] Dong " + str(row_num) + ": Khong sinh duoc config")
            continue

        layout = config.get("slides", [{}])[0].get("layout", "?")
        print("[INFO] Layout GPT chon: " + layout)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            pngs = render_slides(config, tmp_dir)
            if not pngs:
                print("[ERROR] Dong " + str(row_num) + ": Render that bai")
                continue

            fb_id = upload_to_facebook(pngs[0])
            if fb_id and "IMAGE_PATH_1" in headers:
                sheet.update_cell(row_num, headers.index("IMAGE_PATH_1") + 1, fb_id)
                print("[OK] IMAGE_PATH_1 = " + fb_id)

        print("[OK] Dong " + str(row_num) + " single post xong! Layout: " + layout)

print("\n[INFO] image_gen_carousel.py hoan thanh.")
