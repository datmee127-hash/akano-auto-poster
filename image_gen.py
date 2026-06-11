"""
image_gen.py - AKANO Auto Image Generator (unified)
"""

import os
import json
import random
import subprocess
import tempfile
import gspread
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

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

# Google Drive client
drive = build("drive", "v3", credentials=creds)


def load_folder_map():
    try:
        folders_sheet = spreadsheet.worksheet("FOLDERS")
        records = folders_sheet.get_all_records()
        result = {
            str(r.get("TÊN", "") or r.get("TEN", "") or r.get("Ten", "")).strip().lower():
            str(r.get("FOLDER_ID", "")).strip()
            for r in records if r.get("FOLDER_ID")
        }
        print("[INFO] FOLDER_MAP: " + str(result))
        return result
    except Exception as e:
        print("[WARN] Khong doc duoc tab FOLDERS: " + str(e))
        return {}


FOLDER_MAP = load_folder_map()

FOLDER_ALIASES = {
    "kho":       ["kho", "kho akn", "kho anh", "kho akano", "kho hang"],
    "container": ["container", "cotainer", "cont", "container akn"],
    "vanphong":  ["van phong", "vanphong", "vp", "van phong akn"],
}


def find_folder_id(folder_key):
    aliases = FOLDER_ALIASES.get(folder_key, [folder_key])
    for alias in aliases:
        if alias in FOLDER_MAP:
            return FOLDER_MAP[alias]
    for map_key, fid in FOLDER_MAP.items():
        for alias in aliases:
            if alias in map_key or map_key in alias:
                return fid
    return None


def random_image_from_drive(folder_key):
    folder_id = find_folder_id(folder_key)
    if not folder_id:
        print("[WARN] Khong tim thay Drive folder cho '" + folder_key + "' trong FOLDER_MAP")
        return None
    try:
        result = drive.files().list(
            q="'" + folder_id + "' in parents and mimeType contains 'image/' and trashed=false",
            fields="files(id, name)",
            pageSize=100,
        ).execute()
        files = result.get("files", [])
        if not files:
            print("[WARN] Drive folder '" + folder_key + "' khong co file nao")
            return None
        chosen = random.choice(files)
        print("[INFO] Drive pick: " + chosen["name"] + " (folder: " + folder_key + ")")
        file_bytes = drive.files().get_media(fileId=chosen["id"]).execute()
        ext = chosen["name"].rsplit(".", 1)[-1] if "." in chosen["name"] else "jpg"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix="." + ext, dir="/tmp")
        tmp.write(file_bytes)
        tmp.close()
        return tmp.name
    except Exception as e:
        print("[WARN] Loi lay anh tu Drive '" + folder_key + "': " + str(e))
        return None


REPO_ROOT      = Path(__file__).parent
COMPOSE_SCRIPT = REPO_ROOT / "compose_slide.py"

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


def pick_photo(tieu_de, caption, layout):
    text = (tieu_de + " " + caption[:200]).lower()
    if layout == "SP5":
        folder_key = "vanphong"
    else:
        folder_key = "kho"
        for kw, pool in PHOTO_KEYWORDS.items():
            if kw in text:
                folder_key = pool
                break
    for key in [folder_key, "kho", "container", "vanphong"]:
        folder = PHOTO_POOLS[key]
        photos = list(folder.glob("*.jpg")) + list(folder.glob("*.JPG")) + list(folder.glob("*.jpeg"))
        if photos:
            chosen = random.choice(photos)
            print("[INFO] Local pick: " + chosen.name + " (folder: " + key + ")")
            return str(chosen)
    print("[INFO] Khong co anh local, thu Google Drive...")
    for key in [folder_key, "kho", "container", "vanphong"]:
        path = random_image_from_drive(key)
        if path:
            return path
    print("[WARN] Khong co anh tu Drive lan local")
    return None


def inject_photo_path(config, tieu_de, caption):
    PHOTO_LAYOUTS = {"SP1", "SP2", "SP3", "SP4", "SP5"}
    for slide in config.get("slides", []):
        layout = slide.get("layout", "")
        if layout in PHOTO_LAYOUTS:
            content = slide.get("content", {})
            if not content.get("photo_path"):
                photo = pick_photo(tieu_de, caption, layout)
                if photo:
                    content["photo_path"] = photo
                    slide["content"] = content
                else:
                    print("[INFO] Fallback: " + layout + " -> S4")
                    slide["layout"] = "S4"
                    headline = (tieu_de[:45] + "\nAkano Nguon Hang") if tieu_de else "Nguon Hang\nChinh Ngach"
                    slide["content"] = {
                        "label": "NGUON HANG SI",
                        "headline": headline,
                        "items": [
                            "Hang chinh ngach, co CO/CQ day du",
                            "500+ SKU san kho, giao ngay",
                            "Hoa don VAT - ban duoc moi kenh",
                        ],
                        "cta": "Inbox nhan bang gia si",
                    }
    return config


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
      "cta": "Inbox de nhan tu van nguon hang",
      "footer": "AKANO - NGUON HANG KINH DOANH - akano.vn - 0988.198.158"
    }}
  ]
}
Chi tra JSON thuan, khong giai thich."""

SINGLE_PROMPT = """Ban la creative director AKANO -- kho si gia dung nhap khau B2B.
Chon layout va sinh JSON config cho 1 slide don co anh that. Headline Title Case.

Quy tac chon layout:
- SP1: anh toan khung, text de nhe, overlay navy
- SP2: anh tren / navy block duoi, phan chia ro
- SP3: anh lam nen mo, text noi bat
- SP4: co stats / so lieu kem anh kho
- SP5: co anh nguoi, visual navy manh

KHONG dien photo_path -- he thong tu dong chon anh.

SP4 (Photo Card + stats) -- stats PHAI CO DUNG 3 PHAN TU, label toi da 12 ky tu:
{"topic":"slug","output_dir":"output/slug","caption":"(giu nguyen)","hashtags":["akano"],"slides":[{"layout":"SP4","content":{"label":"LABEL CAPS","headline":"Tieu De Chinh\\n2 Dong","stats":[{"value":"100%","label":"CHINH NGACH"},{"value":"5 Nam","label":"KINH NGHIEM"},{"value":"500+","label":"SKU SAN KHO"}],"cta":"Inbox kiem tra nguon hang","photo_v_anchor":0.5,"photo_full":false}}]}
Bat buoc: mang stats chi co dung 3 phan tu. Vi du label tot: "CHINH NGACH", "CO VAT", "SAN KHO", "5 NAM".

SP5 (VNPAY Hero):
{"topic":"slug","output_dir":"output/slug","caption":"(giu nguyen)","hashtags":["akano"],"slides":[{"layout":"SP5","content":{"label":"LABEL CAPS","headline":"Tieu De\\nNgan Gon\\n2-3 Dong","sub":"Shopee Mall - Sieu thi - B2B","features":["Chinh ngach","Hoa don VAT","CO/CQ day du"],"cta":"Inbox nhan bang gia si","scale_boost":0.85,"person_up":0}}]}

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


# Main

vn_tz        = timezone(timedelta(hours=7))
current_time = datetime.now(vn_tz).strftime("%H:%M")
print("[INFO] Gio Viet Nam: " + current_time)

records = sheet.get_all_records(head=3)
print("[INFO] Doc duoc " + str(len(records)) + " dong tu Sheet")
if records:
    print("[DEBUG] Headers: " + str(list(records[0].keys())))

for i, row in enumerate(records):
    status   = str(row.get("STATUS", "") or row.get("TRANG THAI", "")).strip()
    loai_anh = str(row.get("Status ảnh", "") or row.get("Status anh", "") or row.get("FORMAT", "")).strip().lower()
    gio_dang = str(row.get("GIỜ ĐĂNG", "") or row.get("GIO DANG", "")).strip()
    row_num  = i + 4
    headers  = list(row.keys())

    if status in ("Da dang",):
        continue

    if loai_anh not in ("carousel", "single", "singer-post", "single-post"):
        continue

    if status != "Test ngay":
        if gio_dang != current_time:
            continue
        if status not in ("Chua lam",):
            continue

    tieu_de = str(row.get("TIÊU ĐỀ BÀI", "") or row.get("TIEU DE BAI", "") or row.get("Tieu de", "") or row.get("TIEU DE", "")).strip()
    if not tieu_de:
        for key in headers:
            kl = key.lower()
            if "tieu" in kl and "de" in kl:
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

    config = inject_photo_path(config, tieu_de, caption)

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
