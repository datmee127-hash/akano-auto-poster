"""
image_gen_single.py - AKANO Single Post Generator v2
SP4/SP5 only, anh that tu Google Drive.
Column detection dung unicodedata.normalize de xu ly Unicode Vietnamese.
"""

import os, json, random, subprocess, tempfile, unicodedata
import gspread, requests
from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
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
drive = build("drive", "v3", credentials=creds)
REPO_ROOT      = Path(__file__).parent
COMPOSE_SCRIPT = REPO_ROOT / "compose_slide.py"


def norm(s):
    """Strip Vietnamese diacritics -> ASCII lowercase for safe substring matching."""
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii").lower()


def col_val(row, *keywords):
    """Return first non-empty value from row where ALL keywords appear in normalized key."""
    for k, v in row.items():
        nk = norm(k)
        if all(kw in nk for kw in keywords):
            val = str(v).strip()
            if val: return val
    return ""


# ── Drive photo helpers ────────────────────────────────────────────────────────

def load_folder_map():
    try:
        records = spreadsheet.worksheet("FOLDERS").get_all_records()
        result = {}
        for r in records:
            fid = str(r.get("FOLDER_ID", "")).strip()
            if not fid: continue
            for k, v in r.items():
                nk = norm(k)
                if "ten" in nk or "name" in nk:
                    name = norm(v)
                    if name: result[name] = fid; break
        print("[INFO] FOLDER_MAP: " + str(result))
        return result
    except Exception as e:
        print("[WARN] Khong doc FOLDERS: " + str(e))
        return {}


FOLDER_MAP = load_folder_map()

FOLDER_ALIASES = {
    "kho":       ["kho", "kho akn", "kho anh", "kho akano", "kho hang"],
    "container": ["container", "cotainer", "cont", "container akn"],
    "vanphong":  ["van phong", "vanphong", "vp"],
}

PHOTO_KEYWORDS = {
    "container": "container", "logistics": "container", "nhap khau": "container",
    "nhan vien": "vanphong",  "doi ngu":   "vanphong",  "van phong": "vanphong",
}


def find_folder_id(folder_key):
    fk = norm(folder_key)
    for alias in FOLDER_ALIASES.get(folder_key, [folder_key]):
        na = norm(alias)
        if na in FOLDER_MAP: return FOLDER_MAP[na]
    for map_key, fid in FOLDER_MAP.items():
        for alias in FOLDER_ALIASES.get(folder_key, [folder_key]):
            na = norm(alias)
            if na in map_key or map_key in na: return fid
    return None


def random_image_from_drive(folder_key):
    folder_id = find_folder_id(folder_key)
    if not folder_id:
        print("[WARN] Khong tim thay Drive folder: " + folder_key); return None
    try:
        result = drive.files().list(
            q="'"+folder_id+"' in parents and mimeType contains 'image/' and trashed=false",
            fields="files(id, name)", pageSize=100,
        ).execute()
        files = result.get("files", [])
        if not files: print("[WARN] Folder " + folder_key + " trong"); return None
        chosen = random.choice(files)
        print("[INFO] Drive pick: " + chosen["name"] + " (folder=" + folder_key + ")")
        file_bytes = drive.files().get_media(fileId=chosen["id"]).execute()
        ext = chosen["name"].rsplit(".", 1)[-1] if "." in chosen["name"] else "jpg"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix="."+ext, dir="/tmp")
        tmp.write(file_bytes); tmp.close(); return tmp.name
    except Exception as e:
        print("[WARN] Loi Drive " + folder_key + ": " + str(e)); return None


def pick_photo(tieu_de, caption, layout):
    text = norm(tieu_de + " " + caption[:200])
    folder_key = "vanphong" if layout == "SP5" else "kho"
    for kw, pool in PHOTO_KEYWORDS.items():
        if norm(kw) in text: folder_key = pool; break
    for key in [folder_key, "kho", "container", "vanphong"]:
        path = random_image_from_drive(key)
        if path: return path
    return None


def inject_photo_path(config, tieu_de, caption):
    for slide in config.get("slides", []):
        layout = slide.get("layout", "")
        if layout in {"SP4", "SP5"}:
            content = slide.get("content", {})
            if not content.get("photo_path"):
                photo = pick_photo(tieu_de, caption, layout)
                if photo: content["photo_path"] = photo; slide["content"] = content; print("[INFO] inject: " + photo)
                else: print("[WARN] Khong lay duoc anh cho " + layout)


# ── GPT ──────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Ban la creative director AKANO -- kho si gia dung B2B.

Chi co 2 layout (LUON dung anh that tu Google Drive):
SP4 Photo Card (MAC DINH) -> dung cho tat ca bai: milestone, so lieu, nguon hang, kho, container, hang hoa, kinh doanh.
SP5 VNPAY Hero -> chi khi bai ve nhan su / doi ngu / nhan vien cu the.

SP4 JSON: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],"slides":[{"layout":"SP4","content":{"photo_path":"","label":"<LABEL 2-4 TU CAPS>","headline":"<2 dong Title Case, dung \\n>","stats":[{"value":"<so>","label":"<LABEL>"},{"value":"<so>","label":"<LABEL>"},{"value":"<so>","label":"<LABEL>"}],"cta":"Inbox nhan bang gia si","photo_v_anchor":0.5,"photo_full":false}}]}

SP5 JSON: {"topic":"<slug>","output_dir":"output/<slug>","caption":"<giu nguyen>","hashtags":["akano"],"slides":[{"layout":"SP5","content":{"photo_path":"","scale_boost":0.85,"person_up":0,"label":"<LABEL CAPS>","headline":"<2-3 dong Title Case, dung \\n>","sub":"<3-5 tu>","features":["<f1>","<f2>","<f3>"],"cta":"Inbox nhan bang gia si"}}]}

Quy tac: chi JSON thuan, slug kebab no dau, giu nguyen caption, photo_path de rong.""".strip()


def generate_config(tieu_de, caption):
    res = requests.post("https://api.openai.com/v1/chat/completions",
        headers={"Authorization": "Bearer "+OPENAI_API_KEY, "Content-Type": "application/json"},
        json={"model": "gpt-4o-mini", "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": "Tieu de: "+tieu_de+"\n\nCaption:\n"+caption}
        ], "max_tokens": 900, "temperature": 0.7}, timeout=60)
    data = res.json()
    if "choices" not in data: print("[ERROR] GPT: "+str(data)); return None
    raw = data["choices"][0]["message"]["content"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
    try: return json.loads(raw)
    except Exception as e: print("[ERROR] JSON: "+str(e)); return None


def render_slide(config, tmp_dir):
    config["output_dir"] = str(tmp_dir / "slides")
    cfg = tmp_dir / "cfg.json"
    with open(cfg, "w", encoding="utf-8") as f: json.dump(config, f, ensure_ascii=False, indent=2)
    r = subprocess.run(["python", str(COMPOSE_SCRIPT), "--carousel", str(cfg)], capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0: print("[ERROR] compose_slide:\n"+r.stderr); return None
    pngs = sorted((tmp_dir/"slides").glob("slide_*.png"))
    return pngs[0] if pngs else None


def upload_to_facebook(png_path):
    with open(png_path, "rb") as f:
        r = requests.post("https://graph.facebook.com/v22.0/"+PAGE_ID+"/photos",
            data={"published": "false", "access_token": FB_TOKEN},
            files={"source": ("image.png", f, "image/png")}, timeout=60)
    result = r.json()
    pid = result.get("id")
    if pid: print("[OK] FB: "+str(pid)); return "fb:"+str(pid)
    print("[ERROR] FB: "+str(result)); return None


# ── Main ──────────────────────────────────────────────────────────────────────

records = sheet.get_all_records(head=3)
print("[INFO] "+str(len(records))+" dong")
vn_tz = timezone(timedelta(hours=7))
current_time = datetime.now(vn_tz).strftime("%H:%M")
print("[INFO] Gio VN: "+current_time)

VALID_FORMATS = ("single", "singer-post", "single-post")

for i, row in enumerate(records):
    # Doc "Status anh" column - dung norm() de strip dau
    loai_anh = ""
    for k, v in row.items():
        nk = norm(k)
        if "status" in nk and "anh" in nk:
            loai_anh = norm(v); break
    if loai_anh not in VALID_FORMATS: continue

    # STATUS column
    status_raw = ""
    for k, v in row.items():
        if norm(k) == "status" and "anh" not in norm(k):
            status_raw = str(v).strip(); break
    if not status_raw:
        status_raw = str(row.get("STATUS", "")).strip()
    status_norm = norm(status_raw)

    # GIO DANG
    gio_dang = ""
    for k, v in row.items():
        nk = norm(k)
        if "gio" in nk and "dang" in nk:
            gio_dang = str(v).strip(); break

    # Skip da dang
    if "da dang" in status_norm or "posted" in status_norm: continue

    if status_norm != "test ngay":
        if gio_dang != current_time: continue
        if "chua" not in status_norm and "pending" not in status_norm and "todo" not in status_norm: continue

    row_num = i + 4
    tieu_de = col_val(row, "tieu", "de")
    caption = col_val(row, "caption")
    headers = list(row.keys())

    print("\n[SINGLE] Dong " + str(row_num) + ": " + tieu_de[:60])
    if not caption: print("[WARN] Caption trong"); continue

    config = generate_config(tieu_de or caption[:80], caption)
    if not config: print("[ERROR] Config that bai"); continue

    layout = config.get("slides", [{}])[0].get("layout", "?")
    print("[INFO] Layout: " + layout)
    inject_photo_path(config, tieu_de, caption)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        png = render_slide(config, tmp_dir)
        if not png: print("[ERROR] Render that bai"); continue
        fb_id = upload_to_facebook(png)
        if fb_id:
            # Cap nhat IMAGE_PATH_1
            for j, k in enumerate(headers):
                if norm(k) == "image_path_1" or (norm(k).startswith("image") and "path" in norm(k) and "1" in k):
                    sheet.update_cell(row_num, j+1, fb_id)
                    print("[OK] IMAGE_PATH_1 = " + fb_id); break

    print("[OK] Dong " + str(row_num) + " xong! Layout: " + layout)

print("\n[INFO] image_gen_single.py v2 hoan tat.")