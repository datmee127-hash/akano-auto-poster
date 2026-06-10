"""
post_and_comment.py — Đăng bài + comment ngay lập tức
Test tính khả thi: post live → comment trong vài giây

Usage:
    python post_and_comment.py

Tokens:
- PAGE token  → dùng để đăng bài (fb_config.json → pages[0].access_token)
- USER token  → dùng để comment (fb_config.json → user_token)
  Lấy User token tại: https://developers.facebook.com/tools/explorer/
  Chọn "Mã người dùng" → Generate → copy → chạy: python save_user_token.py
"""

import json
import time
import requests
from pathlib import Path

ROOT        = Path(__file__).parent
CONFIG_FILE = ROOT / "fb_config.json"
OUTPUT_DIR  = ROOT / "output"

# ── Load config ────────────────────────────────────────────────────────────────
with open(CONFIG_FILE, encoding="utf-8") as f:
    fb_cfg = json.load(f)

PAGE         = fb_cfg["pages"][0]
PAGE_ID      = PAGE["page_id"]
TOKEN        = PAGE["access_token"]        # Page token — để đăng bài + comment
USER_TOKEN   = TOKEN                              # Dùng Page token để comment

print(f"📄 Page: {PAGE['name']}")

# ── Chọn carousel ──────────────────────────────────────────────────────────────
# Dùng carousel mới nhất: nguon-hang-tmdt-2026
test_folder = OUTPUT_DIR / "tu-dat-1688-vs-kho-si"
if not test_folder.exists():
    for folder in sorted(OUTPUT_DIR.iterdir()):
        if not folder.is_dir():
            continue
        if list(folder.glob("slide_*.png")):
            test_folder = folder
            break

if not test_folder:
    print("❌ Không tìm thấy carousel trong output/")
    exit(1)

slides   = sorted(test_folder.glob("slide_*.png"))
cap_file = test_folder / "caption.txt"
caption  = cap_file.read_text(encoding="utf-8") if cap_file.exists() else "Bài đăng từ Akano."

print(f"📁 Carousel: {test_folder.name} ({len(slides)} slides)\n")

# ── Upload ảnh ─────────────────────────────────────────────────────────────────
print("📤 Upload ảnh...")
photo_ids = []
for slide in slides:
    with open(slide, "rb") as img:
        resp = requests.post(
            f"https://graph.facebook.com/v19.0/{PAGE_ID}/photos",
            data={"access_token": TOKEN, "published": "false"},
            files={"source": img},
            timeout=60
        )
    result = resp.json()
    if "id" in result:
        photo_ids.append(result["id"])
        print(f"   ✅ {slide.name} → {result['id']}")
    else:
        print(f"   ❌ Lỗi: {result}")

if not photo_ids:
    print("❌ Upload thất bại")
    exit(1)

# ── Đăng bài live ngay ────────────────────────────────────────────────────────
print(f"\n📨 Đăng bài live ({len(photo_ids)} ảnh)...")
attached = [{"media_fbid": pid} for pid in photo_ids]
resp = requests.post(
    "https://graph.facebook.com/v19.0/me/feed",
    data={
        "access_token": TOKEN,
        "message":       caption,
        "attached_media": json.dumps(attached),
        "published":      "true",
    },
    timeout=30
)
post_result = resp.json()

if "id" not in post_result:
    print(f"❌ Đăng bài thất bại: {post_result}")
    exit(1)

post_id = post_result["id"]
print(f"✅ Bài đã live! Post ID: {post_id}")

# ── Comment kèm ảnh ──────────────────────────────────────────────────────────
COMMENT_TEXT  = "📦 Akano — Nguồn hàng gia dụng nhập khẩu chính ngạch.\n✅ VAT đầy đủ · CO/CQ · 500+ SKU · Giao toàn quốc\n📩 Inbox 'BÁO GIÁ' để nhận bảng giá sỉ tháng 6 ngay!"
COMMENT_IMAGE = r"H:\ChatGPT Image 11_09_37 4 thg 6, 2026.png"

print(f"\n💬 Comment kèm ảnh...")
time.sleep(2)

# Bước 1: Upload ảnh comment (unpublished)
comment_photo_id = None
img_path = Path(COMMENT_IMAGE)
if img_path.exists():
    print(f"   📤 Upload ảnh comment: {img_path.name}")
    with open(img_path, "rb") as img:
        resp = requests.post(
            f"https://graph.facebook.com/v19.0/{PAGE_ID}/photos",
            data={"access_token": TOKEN, "published": "false"},
            files={"source": img},
            timeout=60
        )
    upload_result = resp.json()
    if "id" in upload_result:
        comment_photo_id = upload_result["id"]
        print(f"   ✅ Ảnh uploaded: {comment_photo_id}")
    else:
        print(f"   ⚠️ Upload ảnh thất bại: {upload_result} — comment text only")
else:
    print(f"   ⚠️ Không tìm thấy ảnh: {COMMENT_IMAGE} — comment text only")

# Bước 2: Post comment
comment_data = {"access_token": USER_TOKEN, "message": COMMENT_TEXT}
if comment_photo_id:
    comment_data["attachment_id"] = comment_photo_id

resp = requests.post(
    f"https://graph.facebook.com/v19.0/{post_id}/comments",
    data=comment_data,
    timeout=15
)
comment_result = resp.json()

if "id" in comment_result:
    print(f"✅ Comment thành công! Comment ID: {comment_result['id']}")
    print(f"\n🎉 XONG! Kiểm tra page:")
    print(f"   https://www.facebook.com/{post_id.replace('_', '/posts/')}")
else:
    print(f"❌ Comment thất bại: {comment_result}")
