"""
image_gen_carousel.py — AKANO Auto Carousel Generator
Đọc Sheet rows STATUS="Chờ tạo carousel"
→ Gọi GPT-4o-mini sinh JSON config
→ Chạy compose_slide.py render 4 PNGs
→ Upload lên Drive
→ Cập nhật IMAGE_PATH, IMAGE_PATH_2, IMAGE_PATH_3, IMAGE_PATH_4 + STATUS="Chưa làm"
"""

import os
import json
import subprocess
import tempfile
import gspread
import requests
from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ── Secrets ───────────────────────────────────────────────────────────────────

OPENAI_API_KEY  = os.environ["OPENAI_API_KEY"]
DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]   # Folder lưu ảnh carousel đã render

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

drive = build("drive", "v3", credentials=creds)

# ── Đường dẫn script + assets (trong repo GitHub) ────────────────────────────

REPO_ROOT     = Path(__file__).parent          # thư mục chứa script này
COMPOSE_SCRIPT = REPO_ROOT / "automation" / "compose_slide.py"

# ── System prompt cho GPT ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """
Bạn là creative director cho thương hiệu AKANO — kho sỉ gia dụng nhập khẩu B2B.
Nhiệm vụ: dựa vào tiêu đề và caption bài đăng, sinh ra JSON config cho tool render carousel 4 slide.

Brand voice: Người trong nghề nói với người đang kinh doanh — thẳng, thực chiến, không hoa mỹ.
Audience: chủ shop online, seller TMĐT, chủ kho sỉ, đại lý phân phối.
Visual: Editorial magazine B2B — Navy #1A2D5A, Red #ED1C24, White. Headline Title Case Bold.

JSON schema bắt buộc:
{
  "topic": "<slug-không-dấu>",
  "output_dir": "output/<slug>",
  "caption": "<nội dung caption từ input, giữ nguyên>",
  "hashtags": ["akano", "nguonhangsi", ...],
  "slides": [
    {
      "layout": "L1",
      "content": {
        "headline": "<tiêu đề lớn 3-5 từ/dòng, 2-3 dòng>",
        "sub_hook": "<câu phụ 1-2 dòng>",
        "body": ["<điểm 1>", "<điểm 2>", "<điểm 3>"]
      }
    },
    {
      "layout": "L2",
      "content": {
        "headline": "<tiêu đề slide 2>",
        "items": ["<mục 1 — hậu quả>", "<mục 2>", "<mục 3>"]
      }
    },
    {
      "layout": "L3",
      "content": {
        "headline": "<tiêu đề slide 3>",
        "cards": [
          {"title": "<tên ngắn>", "body": "<giải thích ngắn>"},
          {"title": "<tên ngắn>", "body": "<giải thích ngắn>", "highlight": true},
          {"title": "<tên ngắn>", "body": "<giải thích ngắn>"},
          {"title": "<tên ngắn>", "body": "<giải thích ngắn>"}
        ]
      }
    },
    {
      "layout": "L5",
      "content": {
        "headline": "<CTA headline 2-3 dòng>",
        "subtext": "<câu kết 1-2 dòng>",
        "cta": "Inbox nhận tư vấn",
        "footer": "AKANO • NGUỒN HÀNG KINH DOANH • akano.vn • 0988.198.158"
      }
    }
  ]
}

Quy tắc:
- Slide 1 (L1): Hook mạnh, gây tò mò, đụng pain point
- Slide 2 (L2): Liệt kê vấn đề / lý do / dấu hiệu (3 items)
- Slide 3 (L3): Phân tích sâu hơn qua 4 cards
- Slide 4 (L5): CTA rõ, kêu gọi inbox
- Headline Title Case, không CAPS toàn bộ
- Chỉ trả về JSON thuần, không giải thích thêm
""".strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_config(tieu_de: str, caption: str) -> dict | None:
    """Gọi GPT-4o-mini sinh JSON config carousel."""
    user_msg = f"Tiêu đề bài: {tieu_de}\n\nCaption:\n{caption}"

    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 1200,
            "temperature": 0.7,
        },
        timeout=60,
    )
    data = res.json()
    if "choices" not in data:
        print(f"[ERROR] GPT lỗi: {data}")
        return None

    raw = data["choices"][0]["message"]["content"].strip()

    # Strip markdown code block nếu GPT trả về ```json...```
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Parse JSON thất bại: {e}\nRaw:\n{raw}")
        return None


def render_carousel(config: dict, tmp_dir: Path) -> list[Path]:
    """
    Lưu config JSON vào tmp_dir, chạy compose_slide.py.
    Trả về list các file PNG đã render (sorted theo tên).
    """
    config_path = tmp_dir / "carousel_config.json"
    # Ghi output vào tmp_dir
    config["output_dir"] = str(tmp_dir / "slides")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"[INFO] Chạy compose_slide.py với config: {config_path}")
    result = subprocess.run(
        ["python", str(COMPOSE_SCRIPT), "--carousel", str(config_path)],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"[ERROR] compose_slide.py failed:\n{result.stderr}")
        return []

    out_dir = tmp_dir / "slides"
    pngs = sorted(out_dir.glob("slide_*.png"))
    print(f"[INFO] Render xong: {[p.name for p in pngs]}")
    return pngs


def upload_png_to_drive(png_path: Path, filename: str) -> str | None:
    """Upload PNG lên Drive, set public, trả về direct download URL."""
    media = MediaFileUpload(str(png_path), mimetype="image/png")
    file  = drive.files().create(
        body={"name": filename, "parents": [DRIVE_FOLDER_ID]},
        media_body=media,
        fields="id",
    ).execute()
    file_id = file["id"]

    drive.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    print(f"[OK] Upload Drive: {filename} → {url}")
    return url


# ── Main ──────────────────────────────────────────────────────────────────────

records = sheet.get_all_records(head=3)
print(f"[INFO] Đọc được {len(records)} dòng từ Sheet")

for i, row in enumerate(records):
    status = str(row.get("STATUS", "")).strip()
    if status != "Chờ tạo carousel":
        continue

    row_num  = i + 4
    tieu_de  = str(row.get("TIÊU ĐỀ BÀI", "")).strip()
    caption  = str(row.get("CAPTION ĐẦY ĐỦ", "")).strip()
    headers  = list(row.keys())

    print(f"\n[INFO] Xử lý dòng {row_num}: {tieu_de}")

    if not caption:
        print("[WARN] Caption trống, bỏ qua")
        continue

    # 1. Sinh JSON config
    print("[INFO] Gọi GPT sinh JSON config...")
    config = generate_config(tieu_de or caption[:80], caption)
    if not config:
        print(f"[ERROR] Dòng {row_num}: Không sinh được config, bỏ qua")
        continue

    # 2. Render slides
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pngs = render_carousel(config, tmp_dir)

        if not pngs:
            print(f"[ERROR] Dòng {row_num}: Render thất bại")
            continue

        # 3. Upload từng PNG lên Drive + cập nhật Sheet
        topic = config.get("topic", f"row{row_num}")
        img_cols = ["IMAGE_PATH", "IMAGE_PATH_2", "IMAGE_PATH_3", "IMAGE_PATH_4"]

        for idx, png_path in enumerate(pngs[:4]):
            col_name = img_cols[idx]
            filename = f"{topic}_slide{idx+1}.png"
            url = upload_png_to_drive(png_path, filename)
            if url and col_name in headers:
                sheet.update_cell(row_num, headers.index(col_name) + 1, url)
                print(f"[OK] {col_name} → {url}")

    # 4. Đổi STATUS
    sheet.update_cell(row_num, headers.index("STATUS") + 1, "Chưa làm")
    print(f"[OK] Dòng {row_num} sẵn sàng đăng!")

print("\n[INFO] image_gen_carousel.py hoàn tất.")
