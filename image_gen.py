"""
image_gen.py - AKANO Auto Image Generator (unified)
Doc tung row trong Sheet:
  - Skip neu STATUS = "Da dang"
  - Doc "Status anh":
      "carousel"    -> gen 4 anh -> IMAGE_PATH_1..4
      "singer-post" -> gen 1 anh -> IMAGE_PATH_1
  - Upload len Facebook (fb:ID), poster.py se dung luc dang bai
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

# ── System Prompts ────────────────────────────────────────────────────────────

CAROUSEL_PROMPT = """
Ban la creative director cho thuong hieu AKANO -- kho si gia dung nhap khau B2B.
Sinh JSON config cho carousel 4 slide. Brand: Navy #1A2D5A, Red #ED1C24. Headline Title Case.

JSON schema:
{
  "topic": "<slug>", "output_dir": "output/<slug>",
  "caption": "<giu nguyen>", "hashtags": ["akano"],
  "slides": [
    {"layout":"L1","content":{"headline":"<2-3 dong>","sub_hook":"<1-2 dong>","body":["<d1>","<d2>","<d3>"]}},
    {"layout":"L2","content":{"headline":"<title>","items":["<i1>","<i2>","<i3>"]}},
    {"layout":"L3","content":{"headline":"<title>","cards":[
      {"title":"<t>","body":"<b>"},{"title":"<t>","body":"<b>","highlight":true},
      {"title":"<t>","body":"<b>"},{"title":"<t>","body":"<b>"}]}},
    {"layout":"L5","content":{"headline":"<CTA 2-3 dong>","subtext":"<1-2 dong>",
      "cta":"Inbox để nhận tư vấn nguồn hàng",
      "footer":"AKANO - NGUỒN HÀNG KINH DOANH - akano.vn - 0988.198.158"}}
  ]
}
Quy tac: Slide1=hook pain point, Slide2=liet ke ly do, Slide3=phan tich 4 cards, Slide4=CTA.
Chi tra JSON thuan.
""".strip()

SINGLE_PROMPT = """
Ban la creative director cho thuong hieu AKANO -- kho si gia dung nhap khau B2B.
Chon layout phu hop va sinh JSON config cho 1 slide don. Brand: Navy #1A2D5A, Red #ED1C24. Headline Title Case.

Layout rules:
S1 = 1 cau insight co dong viral  |  S2 = bai viet suy nghi thuan text
S3 = so lieu/milestone             |  S4 = meo/checklist co bullets

JSON schema theo layout:

S1: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],
     "slides":[{"layout":"S1","content":{"quote":"<2-8 tu x 1-3 dong, dung \\n>","attribution":"— AKANO · Nguồn hàng kinh doanh"}}]}

S2: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],
     "slides":[{"layout":"S2","content":{"title":"<2-3 dong Title Case>","body":["<doan1>","<doan2>","<doan3>"],"cta":"Inbox để chia sẻ thêm"}}]}

S3: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],
     "slides":[{"layout":"S3","content":{"label":"<LABEL CAPS>","big_number":"<max 8 ky tu>","caption":"<3-6 tu>","subtext":"<12-18 tu>"}}]}

S4: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],
     "slides":[{"layout":"S4","content":{"label":"<LABEL CAPS>","headline":"<2 dong, dung \\n>","items":["<i1>","<i2>","<i3>"],"cta":"Inbox để Akano tư vấn"}}]}

Chi tra JSON thuan.
""".strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def call_gpt(system_prompt, tieu_de, caption):
    user_msg = "Tieu de: " + tieu_de + "\n\nCaption:\n" + caption
    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer " + OPENAI_API_KEY, "Content-Type": "application/json"},
        json={"model": "gpt-4o-mini",
              "messages": [{"role": "system", "content": system_prompt},
                           {"role": "user",   "content": user_msg}],
              "max_tokens": 1200, "temperature": 0.7},
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

records = sheet.get_all_records(head=3)
print("[INFO] Doc duoc " + str(len(records)) + " dong tu Sheet")

for i, row in enumerate(records):
    status    = str(row.get("STATUS", "")).strip()
    loai_anh  = str(row.get("Status anh", "") or row.get("Status ảnh", "")).strip().lower()
    row_num   = i + 4
    headers   = list(row.keys())

    # Skip bai da dang
    if status in ("Đã đăng", "Da dang"):
        continue

    # Chi xu ly row co Status anh hop le
    if loai_anh not in ("carousel", "single", "singer-post", "single-post"):
        continue

    tieu_de = str(row.get("TIÊu ĐỀ BÀI", "") or row.get("TIEU DE BAI", "")).strip()
    caption = str(row.get("CAPTION ĐẦY ĐỦ", "") or row.get("CAPTION DAY DU", "")).strip()

    print("\n[INFO] Dong " + str(row_num) + " | Loai: " + loai_anh + " | " + tieu_de[:50])

    if not caption:
        print("[WARN] Caption trong, bo qua")
        continue

    is_carousel = (loai_anh == "carousel")
    system_prompt = CAROUSEL_PROMPT if is_carousel else SINGLE_PROMPT

    print("[INFO] Goi GPT...")
    config = call_gpt(system_prompt, tieu_de or caption[:80], caption)
    if not config:
        print("[ERROR] Khong sinh duoc config, bo qua")
        continue

    layout = config.get("slides", [{}])[0].get("layout", "?")
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
