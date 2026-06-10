"""
image_gen_single.py - AKANO Auto Single Post Generator
Doc Sheet rows "Status anh"="single/singer-post/single-post"
-> GPT chon layout + sinh JSON config
-> compose_slide.py render 1 PNG
-> Upload len Facebook as unpublished photo
-> Cap nhat IMAGE_PATH_1

Layouts:
  Graphic (khong anh): S1 Quote / S2 Insight / S3 Stat / S4 Tip
  Photo-based (anh that): SP1 Full Overlay / SP2 Split / SP3 Blur / SP4 Photo Card / SP5 VNPAY Hero
  SP layouts chi kha dung neu folder "Anh that" ton tai (local). Tren GitHub Actions se fallback S-layouts.
"""

import os
import json
import random
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

# ── Photo pools (chi kha dung khi chay local, co folder Anh that) ─────────────
_BASE = REPO_ROOT.parent

PHOTO_POOLS = {
    "kho":       _BASE / "Anh that" / "KHO AKN",
    "container": _BASE / "Anh that" / "Cotainer",
    "vanphong":  _BASE / "Anh that" / "Van phong",
}

PHOTO_KEYWORDS = {
    "container":  "container",
    "logistics":  "container",
    "nhap khau":  "container",
    "nhan vien":  "vanphong",
    "doi ngu":    "vanphong",
    "van phong":  "vanphong",
}

# Kiem tra co anh that khong (de quyet dinh dung SP hay S layout)
_HAS_PHOTOS = any(
    ((_BASE / "Anh that" / sub).exists() or
     (_BASE / "Ảnh thật" / sub).exists())
    for sub in ["KHO AKN", "Cotainer"]
)

# Thu them path co dau
if not _HAS_PHOTOS:
    PHOTO_POOLS = {
        "kho":       _BASE / "Ảnh thật" / "KHO AKN",
        "container": _BASE / "Ảnh thật" / "Cotainer",
        "vanphong":  _BASE / "Ảnh thật" / "Văn phòng",
    }
    _HAS_PHOTOS = PHOTO_POOLS["kho"].exists()

print("[INFO] Photo pools kha dung: " + str(_HAS_PHOTOS))


def pick_photo(tieu_de, caption, layout):
    """Chon random 1 anh that phu hop voi content. Tra None neu khong co anh."""
    text = (tieu_de + " " + caption[:200]).lower()
    if layout == "SP5":
        folder_key = "vanphong"
    else:
        folder_key = "kho"
        for kw, pool in PHOTO_KEYWORDS.items():
            if kw in text:
                folder_key = pool
                break
    folder = PHOTO_POOLS[folder_key]
    if not folder.exists():
        print("[WARN] Folder khong ton tai: " + str(folder))
        return None
    photos = list(folder.glob("*.jpg")) + list(folder.glob("*.JPG")) + list(folder.glob("*.jpeg"))
    if not photos:
        print("[WARN] Khong co anh trong: " + str(folder))
        return None
    chosen = random.choice(photos)
    print("[INFO] Auto-pick anh: " + chosen.name + " (" + folder_key + ")")
    return str(chosen)


def inject_photo_path(config, tieu_de, caption):
    """Tu fill photo_path cho SP layouts neu chua co."""
    SP_LAYOUTS = {"SP1", "SP2", "SP3", "SP4", "SP5"}
    for slide in config.get("slides", []):
        layout = slide.get("layout", "")
        if layout in SP_LAYOUTS:
            content = slide.get("content", {})
            if not content.get("photo_path"):
                path = pick_photo(tieu_de, caption, layout)
                if path:
                    content["photo_path"] = path
                    slide["content"] = content
                else:
                    print("[WARN] Khong tim duoc anh, layout " + layout + " co the loi")
    return config


# ── System Prompt ─────────────────────────────────────────────────────────────

_SP_SECTION = """
SP1 Full Overlay  -> anh kho/container, text overlay navy, visual manh
SP2 Photo Split   -> anh tren / navy block text duoi
SP3 Blur BG       -> anh lam nen mo, text noi bat
SP4 Photo Card    -> co stats 3 cot + anh kho -- tot nhat cho B2B authority
SP5 VNPAY Hero    -> chi dung khi content lien quan nhan su / doi ngu (co anh nguoi)

SP JSON schema (KHONG dien photo_path -- he thong tu chon):
SP1/SP2/SP3:
{"layout":"SP1","content":{"label":"LABEL CAPS","headline":"Tieu De\\n2 Dong","items":["Diem 1","Diem 2","Diem 3"],"cta":"Inbox de tu van nguon hang"}}
SP4:
{"layout":"SP4","content":{"label":"LABEL CAPS","headline":"Tieu De\\n2 Dong","stats":[{"value":"100%","label":"CHINH NGACH"},{"value":"5 Nam","label":"KINH NGHIEM"},{"value":"500+","label":"SKU SAN KHO"}],"cta":"Inbox kiem tra nguon hang","photo_v_anchor":0.5,"photo_full":false}}
SP5:
{"layout":"SP5","content":{"label":"LABEL CAPS","headline":"Tieu De\\nNgan\\n2-3 Dong","sub":"Shopee Mall · Sieu thi · B2B","features":["Chinh ngach","Hoa don VAT","CO/CQ day du"],"cta":"Inbox nhan bang gia si","scale_boost":0.85,"person_up":0}}
""" if _HAS_PHOTOS else ""

_SP_RULE = """
SP1/SP2/SP3/SP4 -> khi topic lien quan kho hang, nhap hang, nguon hang (co anh that)
SP5             -> chi khi topic lien quan nhan su, doi ngu (co anh nguoi)
""" if _HAS_PHOTOS else ""

SYSTEM_PROMPT = """
Ban la creative director cho thuong hieu AKANO -- kho si gia dung nhap khau B2B.
Nhiem vu: chon layout phu hop va sinh JSON config cho 1 slide don.

Brand: Navy #1A2D5A, Red #ED1C24. Headline Title Case.
Audience: chu shop, seller TMDT, chu kho si, dai ly.

--- LAYOUT RULES ---
S1 Quote Card    -> 1 cau insight co dong, viral/share
S2 Insight Card  -> suy nghi, goc nhin, triet ly (thuan text)
S3 Stat          -> so lieu lon, milestone, countdown
S4 Tip Card      -> meo, checklist, huong dan thuc chien
""".strip() + _SP_RULE + """

--- JSON SCHEMA ---

S1: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],"slides":[{"layout":"S1","content":{"quote":"<2-8 tu x 1-3 dong dung \\n>","attribution":"— AKANO · Nguồn hàng kinh doanh"}}]}

S2: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],"slides":[{"layout":"S2","content":{"title":"<2-3 dong Title Case dung \\n>","body":["<doan 1>","<doan 2>","<doan 3>"],"cta":"Inbox để chia sẻ thêm"}}]}

S3: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],"slides":[{"layout":"S3","content":{"label":"<LABEL CAPS>","big_number":"<max 8 ky tu>","caption":"<3-6 tu>","subtext":"<12-18 tu>"}}]}

S4: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],"slides":[{"layout":"S4","content":{"label":"<LABEL CAPS>","headline":"<2 dong dung \\n>","items":["<6-12 tu>","...","..."],"cta":"Inbox để Akano tư vấn"}}]}
""".strip() + _SP_SECTION + """

Chi tra JSON thuan, khong giai thich. Slug kebab-case khong dau. Giu nguyen caption.
""".strip()


def generate_config(tieu_de, caption):
    user_msg = "Tieu de bai: " + tieu_de + "\n\nCaption:\n" + caption
    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer " + OPENAI_API_KEY, "Content-Type": "application/json"},
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 900,
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
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print("[ERROR] compose_slide.py failed:\n" + result.stderr)
        return None
    out_dir = tmp_dir / "slides"
    pngs = list(out_dir.glob("slide_1_*.png")) or list(out_dir.glob("slide_*.png"))
    if not pngs:
        print("[ERROR] Khong tim thay PNG output")
        return None
    print("[INFO] Render xong: " + pngs[0].name)
    return pngs[0]


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
        print("[OK] Upload Facebook: " + str(photo_id))
        return "fb:" + str(photo_id)
    print("[ERROR] Upload that bai: " + str(result))
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

records = sheet.get_all_records(head=3)
print("[INFO] Doc duoc " + str(len(records)) + " dong tu Sheet")

for i, row in enumerate(records):
    loai_anh = str(row.get("Status anh", "") or row.get("Status ảnh", "")).strip().lower()
    if loai_anh not in ("single", "singer-post", "single-post"):
        continue

    status = str(row.get("STATUS", "")).strip()
    if status in ("Đ\xe3 đăng", "Da dang"):
        continue

    row_num = i + 4
    headers = list(row.keys())
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

    print("\n[INFO] Dong " + str(row_num) + ": " + tieu_de[:60])

    if not caption:
        print("[WARN] Caption trong, bo qua")
        continue

    config = generate_config(tieu_de or caption[:80], caption)
    if not config:
        print("[ERROR] Khong sinh duoc config, bo qua")
        continue

    layout = config.get("slides", [{}])[0].get("layout", "?")
    print("[INFO] Layout: " + layout)

    # Auto-fill photo cho SP layouts
    config = inject_photo_path(config, tieu_de, caption)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        png = render_single(config, tmp_dir)
        if not png:
            print("[ERROR] Render that bai")
            continue
        fb_id = upload_to_facebook(png)
        if fb_id and "IMAGE_PATH_1" in headers:
            sheet.update_cell(row_num, headers.index("IMAGE_PATH_1") + 1, fb_id)
            print("[OK] IMAGE_PATH_1 = " + fb_id)

    print("[OK] Dong " + str(row_num) + " xong! Layout: " + layout)

print("\n[INFO] image_gen_single.py hoan tat.")
