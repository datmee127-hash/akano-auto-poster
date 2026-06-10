"""
Akano Carousel Slide Composer — v1.0
Generates brand-perfect slides (output 1350px) with correct logo + fonts + colors.

Usage:
    # Full carousel from JSON config
    python compose_slide.py --carousel configs/re-nhat-van-lo.json

    # Single slide
    python compose_slide.py --layout L1 --headline "RẺ NHẤT VẪN LỖ" --out slide1.png
"""

import argparse
import io
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ============================================================================
# CONSTANTS — Akano Brand v1.3 (Editorial style — T5/2026)
# ============================================================================

# Slide dimensions — per-layout map (v1.5 T5/2026):
# Render CANVAS ở 1800px (font/layout calibrated), OUTPUT_SCALE = 0.75 → output file 1350px.
# Carousel 4 slides — slide 1 landscape 3:2 (output 1350×900), slides 2-4 vuông 1:1 (output 1350×1350).
LAYOUT_DIMS = {
    # Carousel layouts (4 slides per carousel — L1 hero + L2/L3/L5 body)
    "L1": (1800, 1200),  # 3:2 landscape — hero (output: 1350×900)
    "L2": (1800, 1800),  # 1:1 square — body (output: 1350×1350)
    "L3": (1800, 1800),  # 1:1 square — body (output: 1350×1350)
    "L4": (1800, 1800),  # 1:1 square — body compare (output: 1350×1350)
    "L5": (1800, 1800),  # 1:1 square — CTA (output: 1350×1350)
    # Single post layouts (4:5 portrait — chuẩn FB feed)
    "S1": (1800, 2250),  # Quote Card — 1 câu insight viral (output: 1350×1688)
    "S2": (1800, 2250),  # Insight Card — chia sẻ insight dài (output: 1350×1688)
    "S3": (1800, 2250),  # Announcement / Stat — số liệu lớn (output: 1350×1688)
    "S4": (1800, 2250),  # Tip Card — 1 mẹo thực chiến (output: 1350×1688)
    # Single post — photo-based layouts (4:5 portrait, same dims as S-series)
    "SP1": (1800, 2250),  # Photo bg + semi-transparent navy overlay on lower portion
    "SP2": (1800, 2250),  # Photo top half + solid navy block bottom half
    "SP3": (1800, 2250),  # Full blurred/darkened photo bg, text on top
    "SP4": (1800, 2250),  # Product-card: white bg, 2-tone headline, full-width hero, stats bar, navy footer
    "SP5": (1800, 2250),  # VNPAY-style: navy gradient bg + auto cutout person + bold headline + pills
}
# Default for single-slide CLI mode + helpers fallback
W, H = LAYOUT_DIMS["L1"]

# Editorial slide palette — softer, magazine-grade B2B
NAVY = "#1A2D5A"       # Primary dark bg (editorial hero, CTA)
NAVY_DEEP = "#0F1E40"  # Gradient bottom, deeper variant
BLUE = "#005EA8"       # Accent only (rarely used on slides now)
RED = "#ED1C24"        # Accent line, sub-hook, CTA button, X marks
SKY = "#0066B3"
LIGHT_SKY = "#90C4E8"  # Body subtext on dark bg, swipe hint
BODY_LIGHT = "#B8C5D6" # Softer body subtext on dark navy
WHITE = "#FFFFFF"
LIGHT_GRAY = "#F4F5F7" # Pale gray bg for content slides
MEDIUM_GRAY = "#8C96A4"
DARK_GRAY = "#2D3748"  # Body text on light bg
DIVIDER = "#E5E7EB"

# Paths
ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
LOGO_PATH = ASSETS / "logoakano-ngang.png"
OUTPUT_DIR = ROOT / "output"

# Font paths
FONT_EXTRABOLD = str(FONTS / "BeVietnamPro-ExtraBold.ttf")
FONT_BOLD = str(FONTS / "BeVietnamPro-Bold.ttf")
FONT_SEMIBOLD = str(FONTS / "BeVietnamPro-SemiBold.ttf")
FONT_MEDIUM = str(FONTS / "BeVietnamPro-Medium.ttf")
FONT_REGULAR = str(FONTS / "BeVietnamPro-Regular.ttf")

# Brand signature — auto-append vào cuối mọi caption (giữa body và hashtags)
BRAND_SIGNATURE = """🏪 AKANO – Nguồn hàng kinh doanh
📍 Kho HN: Số 6 ngõ 4, Phố Xốm, Quận Hà Đông, Hà Nội
📍 Kho HCM: Hẻm 92/3, Phan Huy Ích, P.15, Tân Bình, HCM
📞 Hotline: 0988.198.158"""

# Output scale — render at 1800px (font/layout calibrated) then downscale before save.
# 0.75 → 1350px output. Change to 1.0 to revert to full 1800px.
OUTPUT_SCALE = 0.75

# Safe zone — 2x for 1800-wide canvas
SAFE = 100
# Pill dimensions — scaled 2x for 1800-wide canvas (~22% width).
LOGO_PILL_W = 260
LOGO_PILL_H = 130
LOGO_PILL_PADDING = 12
LOGO_PILL_RADIUS = 20

# ============================================================================
# HELPERS
# ============================================================================

def font(path, size):
    """Shortcut to load a TTF font."""
    return ImageFont.truetype(path, size)


def measure(draw, text, fnt):
    """Return (width, height) of text rendered with font fnt."""
    bbox = draw.textbbox((0, 0), text, font=fnt)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(text, fnt, max_width, draw):
    """Wrap text to fit within max_width pixels. Returns list of lines."""
    if "\n" in text:
        # Honor explicit line breaks first
        return [line for raw in text.split("\n") for line in wrap_text(raw, fnt, max_width, draw)]
    words = text.split()
    if not words:
        return [""]
    lines, current = [], words[0]
    for w in words[1:]:
        trial = current + " " + w
        if measure(draw, trial, fnt)[0] <= max_width:
            current = trial
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


def draw_text_block(draw, lines, fnt, fill, top_y, x_anchor, total_width, line_spacing=1.2, align="center"):
    """Draw multi-line text block. Returns bottom-y after drawing."""
    y = top_y
    for line in lines:
        lw, lh = measure(draw, line, fnt)
        if align == "center":
            x = x_anchor - lw / 2
        elif align == "right":
            x = x_anchor - lw
        else:
            x = x_anchor
        draw.text((x, y), line, fill=fill, font=fnt)
        y += lh * line_spacing
    return y


def draw_logo_pill(img, dark_bg=True):
    """Draw white pill at top-right and paste real logo on top. Returns the image."""
    img_w, _ = img.size  # derive from actual canvas — supports per-layout aspect ratios
    draw = ImageDraw.Draw(img)
    pill_x = img_w - SAFE - LOGO_PILL_W
    pill_y = SAFE
    pill_box = (pill_x, pill_y, pill_x + LOGO_PILL_W, pill_y + LOGO_PILL_H)

    if dark_bg:
        # Draw white pill behind logo so brand colors stay readable
        draw.rounded_rectangle(pill_box, radius=LOGO_PILL_RADIUS, fill=WHITE)

    # Load and paste real logo with transparency
    if not LOGO_PATH.exists():
        raise FileNotFoundError(f"Logo not found at {LOGO_PATH}")
    logo = Image.open(LOGO_PATH).convert("RGBA")

    # Auto-crop to alpha bbox — strips the file's internal whitespace so the
    # actual chevron+AKANO+tagline content fills the pill, not the file padding.
    bbox = logo.getchannel("A").getbbox()
    if bbox:
        logo = logo.crop(bbox)

    # Fit logo inside pill with padding
    target_w = LOGO_PILL_W - 2 * LOGO_PILL_PADDING
    target_h = LOGO_PILL_H - 2 * LOGO_PILL_PADDING
    ratio = min(target_w / logo.width, target_h / logo.height)
    new_w = int(logo.width * ratio)
    new_h = int(logo.height * ratio)
    logo = logo.resize((new_w, new_h), Image.LANCZOS)

    # Center the logo inside the pill
    paste_x = pill_x + (LOGO_PILL_W - new_w) // 2
    paste_y = pill_y + (LOGO_PILL_H - new_h) // 2
    img.paste(logo, (paste_x, paste_y), logo)
    return img


def make_gradient(top_color, bottom_color, size=None):
    """Vertical 2-color gradient at given size (defaults to module W, H)."""
    w, h = size if size else (W, H)
    gradient = Image.new("RGB", (w, h), top_color)
    draw = ImageDraw.Draw(gradient)
    top_rgb = Image.new("RGB", (1, 1), top_color).getpixel((0, 0))
    bot_rgb = Image.new("RGB", (1, 1), bottom_color).getpixel((0, 0))
    for y in range(h):
        t = y / (h - 1)
        r = int(top_rgb[0] + (bot_rgb[0] - top_rgb[0]) * t)
        g = int(top_rgb[1] + (bot_rgb[1] - top_rgb[1]) * t)
        b = int(top_rgb[2] + (bot_rgb[2] - top_rgb[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return gradient


def font_size_of(fnt):
    """Return point size of a PIL ImageFont."""
    return getattr(fnt, "size", 40)


def fit_font_size(text, font_path, max_width, start_size, draw, min_size=40):
    """Find largest font size that fits text within max_width (single line)."""
    size = start_size
    while size > min_size:
        f = font(font_path, size)
        if measure(draw, text, f)[0] <= max_width:
            return f
        size -= 8
    return font(font_path, min_size)


def fit_lines_font(explicit_lines, font_path, max_width, size_choices, draw):
    """Pick the largest font from size_choices where every explicit line fits."""
    for size in size_choices:
        f = font(font_path, size)
        if all(measure(draw, ln, f)[0] <= max_width for ln in explicit_lines):
            return f
    return font(font_path, size_choices[-1])


def load_photo(photo_path, target_w, target_h, v_anchor=0.5):
    """Load and cover-crop a photo to exactly fill target_w × target_h.

    v_anchor controls vertical crop position (0.0 = top, 0.5 = center, 1.0 = bottom).
    Use v_anchor=0.1 for portrait/person shots to keep the head visible.
    """
    photo = Image.open(photo_path).convert("RGB")
    pw, ph = photo.size
    scale = max(target_w / pw, target_h / ph)
    new_w, new_h = int(pw * scale), int(ph * scale)
    photo = photo.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    excess_h = new_h - target_h
    top = int(excess_h * v_anchor)
    return photo.crop((left, top, left + target_w, top + target_h))


def draw_accent_line(draw, x, y, length=70, thickness=6, fill=RED):
    """Editorial red accent line — small horizontal bar (magazine signifier)."""
    draw.rectangle((x, y, x + length, y + thickness), fill=fill)


def draw_swipe_hint(draw, canvas_w, canvas_h, on_dark=True, text="Vuốt để xem"):
    """Bottom-right swipe hint with text + triangle arrow. Pass canvas dims explicitly."""
    color = LIGHT_SKY if on_dark else MEDIUM_GRAY
    f = font(FONT_MEDIUM, 44)
    tw, th = measure(draw, text, f)
    arrow_pad = 28
    arrow_size = 16
    total_w = tw + arrow_pad + arrow_size * 2 + 8
    right_edge = canvas_w - SAFE - 8
    bottom_edge = canvas_h - SAFE
    text_x = right_edge - total_w
    text_y = bottom_edge - th - 16
    draw.text((text_x, text_y), text, fill=color, font=f)
    # Triangle arrow pointing right after text
    ax = text_x + tw + arrow_pad
    ay = text_y + th // 2 + 2
    triangle = [
        (ax, ay - arrow_size),
        (ax + arrow_size * 1.6, ay),
        (ax, ay + arrow_size),
    ]
    draw.polygon(triangle, fill=color)


# ============================================================================
# LAYOUT RENDERERS
# ============================================================================

def render_L1(content):
    """L1 Editorial Hero — landscape 3:2 (output 1350×900). Dark navy + Title Case hook + red sub-hook + body."""
    canvas_w, canvas_h = LAYOUT_DIMS["L1"]
    img = Image.new("RGB", (canvas_w, canvas_h), NAVY)
    draw = ImageDraw.Draw(img)

    headline = content.get("headline", "Nhập hàng Trung Quốc\nrẻ nhất thị trường.")
    sub_hook = content.get("sub_hook", "Vậy sao cuối tháng vẫn không có lời?")
    body = content.get("body", [
        "Không phải hàng TQ không tốt.",
        "Không phải thị trường bão hoà.",
        "Vấn đề nằm ở chỗ khác.",
    ])

    # Red accent line (top-left signifier) — 2x for 1800-wide canvas
    draw_accent_line(draw, SAFE + 40, SAFE + 180, length=110, thickness=10, fill=RED)

    # Main hook — Bold, Title Case, white
    # Gioi han width tranh vung logo pill top-right
    text_max_w = canvas_w - 2 * SAFE - LOGO_PILL_W - 100
    # Auto-wrap neu headline khong co explicit newline
    if "\n" in headline:
        explicit_white = headline.split("\n")
    else:
        f_try = font(FONT_BOLD, 96)
        explicit_white = wrap_text(headline, f_try, text_max_w, draw)
    f_head = fit_lines_font(explicit_white, FONT_BOLD, text_max_w, [108, 96, 84, 76, 68], draw)
    line_h = int(font_size_of(f_head) * 1.14)
    y = SAFE + 220
    for ln in explicit_white:
        draw.text((SAFE + 40, y), ln, fill=WHITE, font=f_head)
        y += line_h

    # Sub-hook — Bold, red, slightly smaller than main hook
    if "\n" in sub_hook:
        explicit_red = sub_hook.split("\n")
    else:
        f_try_red = font(FONT_BOLD, 80)
        explicit_red = wrap_text(sub_hook, f_try_red, text_max_w, draw)
    f_sub = fit_lines_font(explicit_red, FONT_BOLD, text_max_w, [88, 80, 72, 64, 56], draw)
    sub_line_h = int(font_size_of(f_sub) * 1.14)
    y += 32  # gap between white and red blocks
    for ln in explicit_red:
        draw.text((SAFE + 40, y), ln, fill=RED, font=f_sub)
        y += sub_line_h

    # Body subtext — 3 short lines, softer color
    f_body = font(FONT_REGULAR, 44)
    y += 48
    for ln in body:
        draw.text((SAFE + 40, y), ln, fill=BODY_LIGHT, font=f_body)
        y += 64

    # Bottom-right swipe hint (disabled)
    # draw_swipe_hint(draw, canvas_w, canvas_h, on_dark=True)

    # Logo (white pill on dark navy bg)
    return draw_logo_pill(img, dark_bg=True)


def render_L2(content):
    """L2 Editorial List — white bg, Title Case headline + numbered list. 1:1 square (output 1350×1350)."""
    canvas_w, canvas_h = LAYOUT_DIMS["L2"]
    img = Image.new("RGB", (canvas_w, canvas_h), WHITE)
    draw = ImageDraw.Draw(img)

    headline = content.get("headline", "Không phải vì 3 lý do này.")
    items = content.get("items", [])

    # Red accent line top-left
    draw_accent_line(draw, SAFE + 40, SAFE + 300, length=110, thickness=10, fill=RED)

    # Headline — Title Case, Bold, Navy
    explicit = headline.split("\n") if "\n" in headline else wrap_text(
        headline, font(FONT_BOLD, 112), canvas_w - 2 * SAFE - 80, draw
    )
    f_head = fit_lines_font(explicit, FONT_BOLD, canvas_w - 2 * SAFE - 80, [112, 100, 88, 80, 72], draw)
    line_h = int(font_size_of(f_head) * 1.18)
    y = SAFE + 360
    for ln in explicit:
        draw.text((SAFE + 40, y), ln, fill=NAVY, font=f_head)
        y += line_h

    # Numbered items — 2x scale
    f_num = font(FONT_BOLD, 80)
    f_body = font(FONT_REGULAR, 56)
    line_h_body = 80
    gap_between_items = 56
    num_block_h = 144
    current_y = y + 56

    for i, item_text in enumerate(items[:3]):
        num = f"0{i+1}"
        num_x = SAFE + 40
        # Red number with small underline
        draw.text((num_x, current_y), num, fill=RED, font=f_num)
        draw.rectangle((num_x, current_y + 112, num_x + 76, current_y + 120), fill=RED)

        # Body text below number — wrap and accumulate height
        body_lines = wrap_text(item_text, f_body, canvas_w - 2 * SAFE - 80, draw)
        body_y = current_y + num_block_h
        for bl in body_lines:
            draw.text((num_x, body_y), bl, fill=DARK_GRAY, font=f_body)
            body_y += line_h_body

        current_y += num_block_h + len(body_lines) * line_h_body + gap_between_items

    # draw_swipe_hint(draw, canvas_w, canvas_h, on_dark=False)
    return draw_logo_pill(img, dark_bg=False)


def render_L3(content):
    """L3 Bento Editorial — pale gray bg, 4 cards, navy highlight card. 1:1 square (output 1350×1350)."""
    canvas_w, canvas_h = LAYOUT_DIMS["L3"]
    img = Image.new("RGB", (canvas_w, canvas_h), LIGHT_GRAY)
    draw = ImageDraw.Draw(img)

    headline = content.get("headline", "Vấn đề thật nằm ở đây.")
    cards = content.get("cards", [])[:4]

    # Red accent line top-left
    draw_accent_line(draw, SAFE + 40, SAFE + 300, length=110, thickness=10, fill=RED)

    # Headline — left-aligned, Title Case, Navy Bold
    explicit = headline.split("\n") if "\n" in headline else wrap_text(
        headline, font(FONT_BOLD, 104), canvas_w - 2 * SAFE - 80, draw
    )
    f_head = fit_lines_font(explicit, FONT_BOLD, canvas_w - 2 * SAFE - 80, [104, 92, 84, 76, 68], draw)
    line_h = int(font_size_of(f_head) * 1.15)
    y = SAFE + 360
    for ln in explicit:
        draw.text((SAFE + 40, y), ln, fill=NAVY, font=f_head)
        y += line_h

    # Bento 2x2 grid
    grid_top = y + 44
    grid_bottom = canvas_h - 160
    grid_left = SAFE
    grid_right = canvas_w - SAFE
    gap = 36
    card_w = (grid_right - grid_left - gap) // 2
    card_h = (grid_bottom - grid_top - gap) // 2

    positions = [
        (grid_left, grid_top),
        (grid_left + card_w + gap, grid_top),
        (grid_left, grid_top + card_h + gap),
        (grid_left + card_w + gap, grid_top + card_h + gap),
    ]

    f_card_title = font(FONT_BOLD, 60)
    f_card_body = font(FONT_REGULAR, 48)

    for i, (cx, cy) in enumerate(positions):
        if i >= len(cards):
            break
        card = cards[i]
        is_highlight = card.get("highlight", False)
        card_bg = NAVY if is_highlight else WHITE
        title_color = WHITE if is_highlight else NAVY
        body_color = BODY_LIGHT if is_highlight else DARK_GRAY

        draw.rounded_rectangle(
            (cx, cy, cx + card_w, cy + card_h),
            radius=28,
            fill=card_bg,
        )

        # Small red accent on each card top-left
        draw.rectangle((cx + 40, cy + 40, cx + 40 + 48, cy + 40 + 8), fill=RED)

        # Card title
        title = card.get("title", "")
        title_lines = wrap_text(title, f_card_title, card_w - 88, draw)
        ty = cy + 88
        for tl in title_lines:
            draw.text((cx + 40, ty), tl, fill=title_color, font=f_card_title)
            ty += 76

        # Card body
        body = card.get("body", "")
        body_lines = wrap_text(body, f_card_body, card_w - 88, draw)
        by = ty + 24
        for bl in body_lines:
            draw.text((cx + 40, by), bl, fill=body_color, font=f_card_body)
            by += 68

    # draw_swipe_hint(draw, canvas_w, canvas_h, on_dark=False)
    return draw_logo_pill(img, dark_bg=True)


def render_L4(content):
    """L4 Split Editorial — top dark navy + Title Case headline, bottom white compare. 1:1 square."""
    canvas_w, canvas_h = LAYOUT_DIMS["L4"]
    img = Image.new("RGB", (canvas_w, canvas_h), WHITE)
    draw = ImageDraw.Draw(img)

    # 44% navy zone gives enough room cho accent line + 2-line headline trong 1:1
    split_y = int(canvas_h * 0.44)
    draw.rectangle((0, 0, canvas_w, split_y), fill=NAVY)

    # Red accent line in dark zone
    draw_accent_line(draw, SAFE + 30, SAFE + 200, length=70, thickness=6, fill=RED)

    headline = content.get("headline_top", "Đúng nguồn\nđổi cục diện.")
    explicit_lines = headline.split("\n")
    f_head = fit_lines_font(explicit_lines, FONT_BOLD, canvas_w - 2 * SAFE - 60, [62, 56, 50, 46, 42], draw)
    line_h = int(font_size_of(f_head) * 1.16)
    # Place headline below accent line (consistent với các slide khác)
    y = SAFE + 240
    for line in explicit_lines:
        draw.text((SAFE + 30, y), line, fill=WHITE, font=f_head)
        y += line_h

    # 2 columns (tighter for 1:1)
    col_top = split_y + 40
    col_left_x = SAFE + 20
    col_right_x = canvas_w // 2 + 20
    col_width = canvas_w // 2 - SAFE - 60

    left_header = content.get("left_header", "Nhập rẻ")
    left_items = content.get("left_items", [])
    right_header = content.get("right_header", "Nhập đúng")
    right_items = content.get("right_items", [])

    f_col_head = font(FONT_BOLD, 44)
    f_col_item = font(FONT_REGULAR, 30)

    # Left column header (red, Title Case)
    draw.text((col_left_x, col_top), left_header, fill=RED, font=f_col_head)
    draw.rectangle((col_left_x, col_top + 56, col_left_x + 46, col_top + 60), fill=RED)
    # Right column header (navy, Title Case)
    draw.text((col_right_x, col_top), right_header, fill=NAVY, font=f_col_head)
    draw.rectangle((col_right_x, col_top + 56, col_right_x + 46, col_top + 60), fill=NAVY)

    # Divider line between columns
    divider_x = canvas_w // 2
    draw.line([(divider_x, col_top + 10), (divider_x, canvas_h - 110)], fill=DIVIDER, width=2)

    # Left items (✗ as red X)
    item_y = col_top + 90
    for it in left_items[:5]:
        cx, cy, r = col_left_x + 12, item_y + 18, 11
        draw.line([(cx - r, cy - r), (cx + r, cy + r)], fill=RED, width=4)
        draw.line([(cx - r, cy + r), (cx + r, cy - r)], fill=RED, width=4)
        lines = wrap_text(it, f_col_item, col_width - 40, draw)
        ty = item_y
        for line in lines:
            draw.text((col_left_x + 44, ty), line, fill=DARK_GRAY, font=f_col_item)
            ty += 40
        item_y = ty + 20

    # Right items (✓ as navy checkmark)
    item_y = col_top + 90
    for it in right_items[:5]:
        cx, cy = col_right_x + 12, item_y + 18
        draw.line([(cx - 11, cy + 2), (cx - 2, cy + 12), (cx + 14, cy - 9)], fill=NAVY, width=4)
        lines = wrap_text(it, f_col_item, col_width - 40, draw)
        ty = item_y
        for line in lines:
            draw.text((col_right_x + 44, ty), line, fill=DARK_GRAY, font=f_col_item)
            ty += 40
        item_y = ty + 20

    # draw_swipe_hint(draw, canvas_w, canvas_h, on_dark=False)
    return draw_logo_pill(img, dark_bg=True)


def render_L5(content):
    """L5 CTA Editorial — gradient dark navy, Title Case headline, red CTA, footer. 1:1 square (output 1350×1350)."""
    canvas_w, canvas_h = LAYOUT_DIMS["L5"]
    img = make_gradient(NAVY, NAVY_DEEP, size=(canvas_w, canvas_h))
    draw = ImageDraw.Draw(img)

    headline = content.get("headline", "Nguồn hàng đúng\n= lợi nhuận bền vững.")
    subtext = content.get("subtext", "Akano sàng lọc 500+ SKU mỗi tháng — bạn chỉ chọn mã đã verify.")
    cta = content.get("cta", "Inbox nhận bảng giá sỉ")
    footer = content.get("footer", "AKANO • NGUỒN HÀNG KINH DOANH • akano.vn • 0988.198.158")

    # Red accent line top-left
    draw_accent_line(draw, SAFE + 40, SAFE + 300, length=110, thickness=10, fill=RED)

    # Headline
    explicit_lines = headline.split("\n")
    f_head = fit_lines_font(explicit_lines, FONT_BOLD, canvas_w - 2 * SAFE - 80, [112, 100, 88, 80, 72], draw)
    line_h = int(font_size_of(f_head) * 1.16)
    y = SAFE + 360
    for line in explicit_lines:
        draw.text((SAFE + 40, y), line, fill=WHITE, font=f_head)
        y += line_h

    # Subtext
    f_sub = font(FONT_REGULAR, 48)
    sub_lines = wrap_text(subtext, f_sub, canvas_w - 2 * SAFE - 80, draw)
    sy = y + 36
    for line in sub_lines:
        draw.text((SAFE + 40, sy), line, fill=BODY_LIGHT, font=f_sub)
        sy += 72

    # CTA button — red rounded rect
    f_cta = font(FONT_BOLD, 68)
    cta_w = measure(draw, cta, f_cta)[0]
    btn_w = min(cta_w + 160, canvas_w - 2 * SAFE - 80)
    btn_h = 152
    btn_x = SAFE + 40
    btn_y = sy + 60
    draw.rounded_rectangle((btn_x, btn_y, btn_x + btn_w, btn_y + btn_h), radius=24, fill=RED)
    cta_h = measure(draw, cta, f_cta)[1]
    draw.text(
        (btn_x + (btn_w - cta_w) / 2, btn_y + (btn_h - cta_h) // 2 - 8),
        cta,
        fill=WHITE,
        font=f_cta,
    )

    # Footer — left-aligned at bottom
    f_foot = font(FONT_REGULAR, 36)
    draw.text((SAFE + 40, canvas_h - SAFE - 64), footer, fill=LIGHT_SKY, font=f_foot)

    # Logo
    return draw_logo_pill(img, dark_bg=True)


# ============================================================================
# SINGLE POST LAYOUTS — S1-S4 (4:5 portrait — render 1800×2250, output 1350×1688)
# ============================================================================

def render_S1(content):
    """S1 Quote Card — 1 câu insight viral. Navy bg, big quote center. (output 1350×1688)"""
    canvas_w, canvas_h = LAYOUT_DIMS["S1"]
    img = Image.new("RGB", (canvas_w, canvas_h), NAVY)
    draw = ImageDraw.Draw(img)

    quote = content.get("quote", "Vấn đề không nằm ở giá.\nNằm ở nguồn.")
    attribution = content.get("attribution", "— AKANO · Nguồn hàng kinh doanh")

    # Red accent line top-left
    draw_accent_line(draw, SAFE + 40, SAFE + 180, length=110, thickness=10, fill=RED)

    # Large opening quote mark (decorative red) — top-left of quote area
    f_mark = font(FONT_BOLD, 220)
    draw.text((SAFE + 30, SAFE + 300), "“", fill=RED, font=f_mark)

    # Quote text — centered vertically in middle 60% of canvas
    explicit_lines = quote.split("\n")
    f_quote = fit_lines_font(explicit_lines, FONT_BOLD, canvas_w - 2 * SAFE - 120, [120, 108, 96, 84, 76, 68], draw)
    line_h = int(font_size_of(f_quote) * 1.18)
    total_h = len(explicit_lines) * line_h
    # Center in vertical 35%-75% band
    band_top = int(canvas_h * 0.40)
    band_bottom = int(canvas_h * 0.78)
    y = band_top + (band_bottom - band_top - total_h) // 2
    for line in explicit_lines:
        lw = measure(draw, line, f_quote)[0]
        # Left-align with safe + 60 indent (matches accent line + quote mark alignment)
        draw.text((SAFE + 60, y), line, fill=WHITE, font=f_quote)
        y += line_h

    # Attribution below quote
    f_attr = font(FONT_MEDIUM, 36)
    draw.text((SAFE + 60, y + 30), attribution, fill=LIGHT_SKY, font=f_attr)

    # Logo top-right
    return draw_logo_pill(img, dark_bg=True)


def render_S2(content):
    """S2 Insight Card — chia sẻ insight dài 3-4 đoạn. White bg + navy title + body. (output 1350×1688)"""
    canvas_w, canvas_h = LAYOUT_DIMS["S2"]
    img = Image.new("RGB", (canvas_w, canvas_h), WHITE)
    draw = ImageDraw.Draw(img)

    title = content.get("title", "Sau 5 năm làm kho sỉ\nmình nhận ra...")
    body = content.get("body", [
        "Đây là đoạn 1 của insight.",
        "Đoạn 2 với góc nhìn cụ thể.",
        "Đoạn 3 với conclusion mạnh."
    ])
    cta = content.get("cta", "")  # Optional

    # Red accent line top-left (cao như SP4)
    draw_accent_line(draw, SAFE + 40, SAFE + 40, length=110, thickness=10, fill=RED)

    # Title — Navy ExtraBold, cỡ lớn như SP4
    explicit_title = title.split("\n")
    f_title = fit_lines_font(explicit_title, FONT_EXTRABOLD, canvas_w - 2 * SAFE - 80, [120, 110, 100, 90, 80], draw)
    title_line_h = int(font_size_of(f_title) * 1.18)
    y = SAFE + 100
    for ln in explicit_title:
        draw.text((SAFE + 40, y), ln, fill=NAVY, font=f_title)
        y += title_line_h

    # Body paragraphs — Regular dark gray
    f_body = font(FONT_REGULAR, 44)
    y += 60
    for para in body:
        body_lines = wrap_text(para, f_body, canvas_w - 2 * SAFE - 80, draw)
        for bl in body_lines:
            draw.text((SAFE + 40, y), bl, fill=DARK_GRAY, font=f_body)
            y += 62
        y += 28  # gap between paragraphs

    # Optional CTA at bottom-left
    if cta:
        f_cta = font(FONT_BOLD, 40)
        cta_w = measure(draw, cta, f_cta)[0]
        btn_h = 96
        btn_w = cta_w + 100
        btn_x = SAFE + 40
        btn_y = canvas_h - SAFE - btn_h - 40
        draw.rounded_rectangle((btn_x, btn_y, btn_x + btn_w, btn_y + btn_h), radius=18, fill=RED)
        cta_h = measure(draw, cta, f_cta)[1]
        draw.text(
            (btn_x + (btn_w - cta_w) / 2, btn_y + (btn_h - cta_h) // 2 - 6),
            cta, fill=WHITE, font=f_cta,
        )

    return draw_logo_pill(img, dark_bg=False)


def render_S3(content):
    """S3 Announcement / Stat Card — big number + caption. Gradient navy. (output 1350×1688)"""
    canvas_w, canvas_h = LAYOUT_DIMS["S3"]
    img = make_gradient(NAVY, NAVY_DEEP, size=(canvas_w, canvas_h))
    draw = ImageDraw.Draw(img)

    big_number = content.get("big_number", "300+ tỷ")
    caption = content.get("caption", "Doanh thu Akano 2025")
    subtext = content.get("subtext", "Tin cậy bởi hàng nghìn chủ shop trên toàn quốc.")
    label = content.get("label", "")  # Optional small label above number

    # Red accent line top-left
    draw_accent_line(draw, SAFE + 40, SAFE + 180, length=110, thickness=10, fill=RED)

    # Optional small red label above big number
    y_anchor = int(canvas_h * 0.32)
    if label:
        f_label = font(FONT_BOLD, 40)
        draw.text((SAFE + 40, y_anchor - 80), label.upper(), fill=RED, font=f_label)

    # Big number — HUGE, center-aligned, red
    f_num = fit_lines_font([big_number], FONT_BOLD, canvas_w - 2 * SAFE - 80, [320, 280, 240, 200, 160], draw)
    num_w = measure(draw, big_number, f_num)[0]
    num_h = font_size_of(f_num)
    # Center horizontally
    draw.text(((canvas_w - num_w) / 2, y_anchor), big_number, fill=RED, font=f_num)

    # Caption below number — white Bold
    y_caption = y_anchor + int(num_h * 1.15)
    f_caption = fit_lines_font([caption], FONT_BOLD, canvas_w - 2 * SAFE - 80, [72, 64, 56, 50, 44], draw)
    cap_w = measure(draw, caption, f_caption)[0]
    draw.text(((canvas_w - cap_w) / 2, y_caption), caption, fill=WHITE, font=f_caption)

    # Subtext below caption — light sky, regular, wrapped
    f_sub = font(FONT_REGULAR, 36)
    y_sub = y_caption + int(font_size_of(f_caption) * 1.4) + 30
    sub_lines = wrap_text(subtext, f_sub, canvas_w - 2 * SAFE - 120, draw)
    for sl in sub_lines:
        slw = measure(draw, sl, f_sub)[0]
        draw.text(((canvas_w - slw) / 2, y_sub), sl, fill=BODY_LIGHT, font=f_sub)
        y_sub += 54

    return draw_logo_pill(img, dark_bg=True)


def render_S4(content):
    """S4 Tip Card — label + headline + bullet list + CTA. Split top navy + bottom white. (output 1350×1688)"""
    canvas_w, canvas_h = LAYOUT_DIMS["S4"]
    img = Image.new("RGB", (canvas_w, canvas_h), WHITE)
    draw = ImageDraw.Draw(img)

    # Top 38% navy zone
    split_y = int(canvas_h * 0.38)
    draw.rectangle((0, 0, canvas_w, split_y), fill=NAVY)

    label = content.get("label", "MẸO KINH DOANH")
    headline = content.get("headline", "3 thứ check trước\nkhi nhập 1 SKU mới")
    items = content.get("items", [])
    cta = content.get("cta", "")  # Optional

    # Red accent in navy zone
    draw_accent_line(draw, SAFE + 40, SAFE + 180, length=110, thickness=10, fill=RED)

    # Small red label above headline
    f_label = font(FONT_BOLD, 40)
    draw.text((SAFE + 40, SAFE + 230), label.upper(), fill=RED, font=f_label)

    # Headline white Bold
    explicit_h = headline.split("\n")
    f_head = fit_lines_font(explicit_h, FONT_BOLD, canvas_w - 2 * SAFE - 80, [88, 80, 72, 64, 56], draw)
    head_line_h = int(font_size_of(f_head) * 1.16)
    y = SAFE + 310
    for ln in explicit_h:
        draw.text((SAFE + 40, y), ln, fill=WHITE, font=f_head)
        y += head_line_h

    # Bottom white zone — bullet items
    bullet_y = split_y + 80
    f_bullet = font(FONT_REGULAR, 48)
    f_num_bullet = font(FONT_BOLD, 56)
    item_spacing = 56
    bullet_block_h = 88

    for i, item_text in enumerate(items[:5]):
        # Red number
        num = f"0{i+1}"
        num_x = SAFE + 40
        draw.text((num_x, bullet_y), num, fill=RED, font=f_num_bullet)
        # Underline under number
        draw.rectangle((num_x, bullet_y + 78, num_x + 60, bullet_y + 86), fill=RED)

        # Body text right of number
        body_x = num_x + 130
        body_w_avail = canvas_w - body_x - SAFE - 20
        body_lines = wrap_text(item_text, f_bullet, body_w_avail, draw)
        by = bullet_y + 8
        for bl in body_lines:
            draw.text((body_x, by), bl, fill=DARK_GRAY, font=f_bullet)
            by += 60

        bullet_y += bullet_block_h + (len(body_lines) - 1) * 60 + item_spacing

    # Optional CTA at bottom
    if cta:
        f_cta = font(FONT_BOLD, 42)
        cta_w = measure(draw, cta, f_cta)[0]
        btn_h = 100
        btn_w = cta_w + 100
        btn_x = SAFE + 40
        btn_y = canvas_h - SAFE - btn_h - 30
        draw.rounded_rectangle((btn_x, btn_y, btn_x + btn_w, btn_y + btn_h), radius=18, fill=RED)
        cta_h = measure(draw, cta, f_cta)[1]
        draw.text(
            (btn_x + (btn_w - cta_w) / 2, btn_y + (btn_h - cta_h) // 2 - 6),
            cta, fill=WHITE, font=f_cta,
        )

    # Logo in top navy zone
    return draw_logo_pill(img, dark_bg=True)


# ============================================================================
# PHOTO-BASED LAYOUTS (SP1 / SP2 / SP3)
# All take content["photo_path"] + label/headline/items/cta same as S4.
# ============================================================================

def _draw_sp_text_block(draw, content, y_start, canvas_w, canvas_h, text_color=WHITE):
    """Shared helper: draws label → headline → numbered items → CTA button."""
    label    = content.get("label", "")
    headline = content.get("headline", "")
    items    = content.get("items", [])
    cta      = content.get("cta", "")

    y = y_start

    # Label
    if label:
        f_label = font(FONT_BOLD, 40)
        draw.text((SAFE + 40, y), label.upper(), fill=RED, font=f_label)
        y += 68

    # Headline
    if headline:
        explicit_h = headline.split("\n")
        f_head = fit_lines_font(explicit_h, FONT_BOLD, canvas_w - 2 * SAFE - 80, [88, 80, 72, 64, 56], draw)
        head_line_h = int(font_size_of(f_head) * 1.18)
        for ln in explicit_h:
            draw.text((SAFE + 40, y), ln, fill=text_color, font=f_head)
            y += head_line_h
        y += 30

    # Numbered items
    if items:
        f_bullet = font(FONT_REGULAR, 48)
        f_num    = font(FONT_BOLD, 54)
        for i, item_text in enumerate(items[:4]):
            num = f"0{i+1}"
            num_x = SAFE + 40
            draw.text((num_x, y), num, fill=RED, font=f_num)
            draw.rectangle((num_x, y + 76, num_x + 58, y + 84), fill=RED)
            body_x = num_x + 130
            body_lines = wrap_text(item_text, f_bullet, canvas_w - body_x - SAFE - 20, draw)
            by = y + 6
            for bl in body_lines:
                draw.text((body_x, by), bl, fill=text_color, font=f_bullet)
                by += 60
            y += 84 + (len(body_lines) - 1) * 60 + 48

    # CTA button
    if cta:
        f_cta = font(FONT_BOLD, 42)
        cta_w  = measure(draw, cta, f_cta)[0]
        btn_h  = 100
        btn_w  = cta_w + 100
        btn_x  = SAFE + 40
        btn_y  = canvas_h - SAFE - btn_h - 30
        draw.rounded_rectangle((btn_x, btn_y, btn_x + btn_w, btn_y + btn_h), radius=18, fill=RED)
        cta_h = measure(draw, cta, f_cta)[1]
        draw.text(
            (btn_x + (btn_w - cta_w) / 2, btn_y + (btn_h - cta_h) // 2 - 6),
            cta, fill=WHITE, font=f_cta,
        )


def render_SP4(content):
    """SP4 — White text zone + full-bleed photo + stats bar + navy footer.
    Set photo_full=true in config to remove white zone and overlay text on photo instead."""
    canvas_w, canvas_h = LAYOUT_DIMS["SP4"]
    photo_path  = content.get("photo_path")
    photo_full  = content.get("photo_full", False)

    label      = content.get("label", "")
    headline   = content.get("headline", "")
    head_lines = headline.split("\n") if headline else []
    stats      = content.get("stats", [])
    cta        = content.get("cta", "Inbox để nhận bảng giá sỉ")
    v_anchor   = content.get("photo_v_anchor", 0.5)

    # Fixed bottom zones
    stats_h  = 256
    footer_h = 230
    red_h    = 14

    pad = 60
    _tmp_draw = ImageDraw.Draw(Image.new("RGB", (canvas_w, canvas_h)))
    avail_w = canvas_w - 2 * pad - 80
    f_head  = fit_lines_font(head_lines, FONT_EXTRABOLD, avail_w,
                             [120, 110, 100, 90, 80], _tmp_draw) if head_lines else None
    lh = int(font_size_of(f_head) * 1.15) if f_head else 0

    if photo_full:
        # ── PHOTO-FULL MODE: photo fills top, text overlaid ───────────
        photo_h     = canvas_h - red_h - stats_h - footer_h
        text_zone_h = 0

        img  = Image.new("RGB", (canvas_w, canvas_h), WHITE)
        if photo_path:
            hero = load_photo(photo_path, canvas_w, photo_h, v_anchor=v_anchor)
            img.paste(hero, (0, 0))

        # Semi-transparent white overlay block behind text (top of photo)
        acc_y      = pad + 30
        lbl_y      = acc_y + 42
        head_start = lbl_y + (50 if label else 0)
        overlay_h  = head_start + (len(head_lines) * lh if head_lines else 0) + 50

        overlay = Image.new("RGBA", (canvas_w, overlay_h), (255, 255, 255, 220))
        img.paste(Image.new("RGB", (canvas_w, overlay_h), WHITE),
                  (0, 0), overlay)

        draw = ImageDraw.Draw(img)

    else:
        # ── STANDARD MODE: separate white text zone above photo ───────
        acc_y      = pad + 40
        lbl_y      = acc_y + 42
        head_start = lbl_y + (52 if label else 0)
        text_zone_h = head_start + (len(head_lines) * lh if head_lines else 0) + 50
        min_photo_h = int(canvas_h * 0.55)
        max_text_zone_h = canvas_h - min_photo_h - red_h - stats_h - footer_h
        text_zone_h = min(text_zone_h, max_text_zone_h)
        photo_h = canvas_h - text_zone_h - red_h - stats_h - footer_h

        img  = Image.new("RGB", (canvas_w, canvas_h), WHITE)
        if photo_path:
            hero = load_photo(photo_path, canvas_w, photo_h, v_anchor=v_anchor)
            img.paste(hero, (0, text_zone_h))

        draw = ImageDraw.Draw(img)

    # ── LOGO (top-right) ─────────────────────────────────────────────
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH).convert("RGBA")
        bbox_l = logo.getchannel("A").getbbox()
        if bbox_l:
            logo = logo.crop(bbox_l)
        r = min(380 / logo.width, 210 / logo.height)
        logo = logo.resize((int(logo.width * r), int(logo.height * r)), Image.LANCZOS)
        img.paste(logo, (canvas_w - pad - logo.width, pad + 20), logo)

    # ── ACCENT + LABEL ────────────────────────────────────────────────
    draw_accent_line(draw, pad + 40, acc_y, length=110, thickness=10, fill=RED)
    if label:
        draw.text((pad + 40, lbl_y), label.upper(), fill=NAVY,
                  font=font(FONT_BOLD, 40))

    # ── HEADLINE 2-tone ───────────────────────────────────────────────
    if f_head and head_lines:
        y = head_start
        for i, ln in enumerate(head_lines):
            draw.text((pad + 40, y), ln,
                      fill=(NAVY if i == 0 else RED), font=f_head)
            y += lh

    # ── RED STRIP ────────────────────────────────────────────────────
    photo_bottom = text_zone_h + photo_h
    draw.rectangle((0, photo_bottom, canvas_w, photo_bottom + red_h), fill=RED)

    # ── STATS BAR ─────────────────────────────────────────────────────
    stats_top = photo_bottom + red_h
    draw.rectangle((0, stats_top, canvas_w, stats_top + stats_h), fill=LIGHT_GRAY)
    if stats:
        col_w = canvas_w // len(stats)
        f_val = font(FONT_EXTRABOLD, 76)
        f_sl  = font(FONT_MEDIUM, 36)
        for j, stat in enumerate(stats):
            cx = col_w * j + col_w // 2
            if j > 0:
                dx = col_w * j
                draw.rectangle((dx, stats_top + 40, dx + 3,
                                 stats_top + stats_h - 40), fill=DIVIDER)
            val = stat.get("value", "")
            vw  = measure(draw, val, f_val)[0]
            draw.text((cx - vw // 2, stats_top + 28), val, fill=NAVY, font=f_val)
            lbl_s = stat.get("label", "")
            lw    = measure(draw, lbl_s, f_sl)[0]
            draw.text((cx - lw // 2, stats_top + 130), lbl_s,
                      fill=MEDIUM_GRAY, font=f_sl)

    # ── FOOTER ────────────────────────────────────────────────────────
    footer_y = stats_top + stats_h
    draw.rectangle((0, footer_y, canvas_w, canvas_h), fill=NAVY)
    f_contact = font(FONT_MEDIUM, 40)
    hotline = "📞  0988.198.158"
    website = "🌐  akano.vn"
    hl_w = measure(draw, hotline, f_contact)[0]
    ws_w = measure(draw, website, f_contact)[0]
    row_x = (canvas_w - hl_w - 100 - ws_w) // 2
    row_y = footer_y + (footer_h - 40) // 2 - 20
    draw.text((row_x, row_y),            hotline, fill=WHITE,      font=f_contact)
    draw.text((row_x + hl_w + 100, row_y), website, fill=BODY_LIGHT, font=f_contact)
    f_cta = font(FONT_BOLD, 44)
    cta_w = measure(draw, cta, f_cta)[0]
    draw.text(((canvas_w - cta_w) // 2, row_y + 66), cta, fill=RED, font=f_cta)

    return img


def render_SP5(content):
    """SP5 — VNPAY-inspired: navy gradient bg, auto background-removal via rembg,
    cutout person right side, bold headline + feature pills + CTA left side."""
    canvas_w, canvas_h = LAYOUT_DIMS["SP5"]
    photo_path = content.get("photo_path") or content.get("cutout_path")

    # ── NAVY GRADIENT BACKGROUND ──────────────────────────────────────
    img  = make_gradient(NAVY, NAVY_DEEP, size=(canvas_w, canvas_h))
    draw = ImageDraw.Draw(img)

    # Decorative concentric ring (right side, behind person)
    ring_cx = int(canvas_w * 0.73)
    ring_cy = int(canvas_h * 0.50)
    for radius, width, color in [
        (680, 90,  (30, 55, 105)),
        (460, 60,  (26, 50,  95)),
        (260, 40,  (22, 44,  85)),
    ]:
        draw.ellipse(
            (ring_cx - radius, ring_cy - radius, ring_cx + radius, ring_cy + radius),
            outline=color, width=width,
        )

    # Left vertical red accent bar
    draw.rectangle((0, int(canvas_h * 0.56), 20, int(canvas_h * 0.82)), fill=RED)

    # ── PERSON CUTOUT via rembg ───────────────────────────────────────
    if photo_path:
        try:
            from rembg import remove as rembg_remove
            with open(photo_path, "rb") as fh:
                raw = fh.read()
            cutout = Image.open(io.BytesIO(rembg_remove(raw))).convert("RGBA")
        except Exception:
            # rembg failed — fall back to raw photo with edge fade
            cutout = Image.open(photo_path).convert("RGBA")

        # Tight-crop: remove empty transparent space around person before scaling
        alpha = cutout.getchannel("A")
        bbox_tight = alpha.getbbox()
        if bbox_tight:
            pad = 30
            w_, h_ = cutout.size
            cutout = cutout.crop((
                max(0, bbox_tight[0] - pad),
                max(0, bbox_tight[1] - pad),
                min(w_, bbox_tight[2] + pad),
                min(h_, bbox_tight[3] + pad),
            ))

        # Scale: fill by height, constrain width, hard-cap inside canvas.
        # scale_boost (JSON, default 1.0) adjusts size — never overflows canvas.
        scale_boost = content.get("scale_boost", 1.0)
        target_h   = min(int(canvas_h * 0.82 * scale_boost), canvas_h - 40)
        target_w_max = int(canvas_w * 0.72)
        sh = target_h / cutout.height
        if int(cutout.width * sh) > target_w_max:
            sh = target_w_max / cutout.width
        new_w = int(cutout.width * sh)
        new_h = int(cutout.height * sh)
        cutout = cutout.resize((new_w, new_h), Image.LANCZOS)
        # Anchor: right side, bottom flush — person_up shifts upward (1 unit = 150px render)
        person_up = content.get("person_up", 0) * 150
        px = max(0, canvas_w - new_w + 80)
        py = canvas_h - new_h - int(person_up)
        base = img.convert("RGBA")
        base.paste(cutout, (px, py), cutout)
        img  = base.convert("RGB")
        draw = ImageDraw.Draw(img)

    # ── LOGO ─────────────────────────────────────────────────────────
    img  = draw_logo_pill(img, dark_bg=True)
    draw = ImageDraw.Draw(img)

    # ── ACCENT + LABEL ────────────────────────────────────────────────
    draw_accent_line(draw, SAFE + 40, SAFE + 180, length=110, thickness=10, fill=RED)
    label = content.get("label", "")
    if label:
        draw.text((SAFE + 40, SAFE + 230), label.upper(),
                  fill=RED, font=font(FONT_BOLD, 42))

    # ── HEADLINE (white, EXTRABOLD, left column only) ─────────────────
    headline   = content.get("headline", "")
    head_lines = headline.split("\n") if headline else []
    head_y = SAFE + (308 if label else 240)
    if head_lines:
        avail_w = int(canvas_w * 0.50)
        f_head  = fit_lines_font(head_lines, FONT_EXTRABOLD, avail_w,
                                 [136, 124, 112, 100, 88], draw)
        lh = int(font_size_of(f_head) * 1.14)
        for ln in head_lines:
            draw.text((SAFE + 40, head_y), ln, fill=WHITE, font=f_head)
            head_y += lh

    # Optional sub-line (red)
    sub = content.get("sub", "")
    if sub:
        f_sub = font(FONT_BOLD, 56)
        draw.text((SAFE + 40, head_y + 28), sub, fill=RED, font=f_sub)

    # ── FEATURE PILLS ─────────────────────────────────────────────────
    features = content.get("features", [])
    if features:
        pill_y = int(canvas_h * 0.73)
        f_pill = font(FONT_MEDIUM, 44)
        for feat in features[:4]:
            fw, fh_ = measure(draw, feat, f_pill)
            pw, ph  = fw + 68, 80
            draw.rounded_rectangle(
                (SAFE + 40, pill_y, SAFE + 40 + pw, pill_y + ph),
                radius=40, outline=RED, width=3,
            )
            draw.text((SAFE + 74, pill_y + (ph - fh_) // 2 - 4),
                      feat, fill=WHITE, font=f_pill)
            pill_y += ph + 22

    # ── CTA BUTTON ────────────────────────────────────────────────────
    cta   = content.get("cta", "Inbox nhận bảng giá sỉ")
    f_cta = font(FONT_BOLD, 46)
    cta_w = measure(draw, cta, f_cta)[0]
    bw, bh = cta_w + 100, 110
    bx = SAFE + 40
    by = canvas_h - SAFE - bh - 24
    draw.rounded_rectangle((bx, by, bx + bw, by + bh), radius=22, fill=RED)
    ch = measure(draw, cta, f_cta)[1]
    draw.text((bx + (bw - cta_w) // 2, by + (bh - ch) // 2 - 6),
              cta, fill=WHITE, font=f_cta)

    return img


def render_SP1(content):
    """SP1 — Full photo + semi-transparent navy overlay on lower 58% of frame."""
    canvas_w, canvas_h = LAYOUT_DIMS["SP1"]
    photo_path = content.get("photo_path")
    if not photo_path:
        raise ValueError("SP1 requires content['photo_path']")

    img = load_photo(photo_path, canvas_w, canvas_h)

    # Semi-transparent navy gradient overlay on lower portion
    overlay_start = int(canvas_h * 0.34)
    overlay = Image.new("RGBA", (canvas_w, canvas_h - overlay_start), (26, 45, 90, 230))
    base = img.convert("RGBA")
    base.paste(overlay, (0, overlay_start), overlay)
    img = base.convert("RGB")

    draw = ImageDraw.Draw(img)
    draw_accent_line(draw, SAFE + 40, overlay_start + 70, length=110, thickness=10, fill=RED)
    _draw_sp_text_block(draw, content, overlay_start + 130, canvas_w, canvas_h, text_color=WHITE)

    return draw_logo_pill(img, dark_bg=True)


def render_SP2(content):
    """SP2 — Photo top 50% + solid navy block bottom 50%, red line at split."""
    canvas_w, canvas_h = LAYOUT_DIMS["SP2"]
    photo_path = content.get("photo_path")
    if not photo_path:
        raise ValueError("SP2 requires content['photo_path']")

    split_y = int(canvas_h * 0.50)

    photo = load_photo(photo_path, canvas_w, split_y)
    img   = Image.new("RGB", (canvas_w, canvas_h), NAVY)
    img.paste(photo, (0, 0))

    draw = ImageDraw.Draw(img)
    # Red accent bar at split
    draw.rectangle((0, split_y - 10, canvas_w, split_y + 2), fill=RED)
    draw_accent_line(draw, SAFE + 40, split_y + 60, length=110, thickness=10, fill=RED)
    _draw_sp_text_block(draw, content, split_y + 120, canvas_w, canvas_h, text_color=WHITE)

    return draw_logo_pill(img, dark_bg=True)


def render_SP3(content):
    """SP3 — Full blurred photo bg + dark navy overlay, text over full frame."""
    canvas_w, canvas_h = LAYOUT_DIMS["SP3"]
    photo_path = content.get("photo_path")
    if not photo_path:
        raise ValueError("SP3 requires content['photo_path']")

    photo = load_photo(photo_path, canvas_w, canvas_h)
    photo = photo.filter(ImageFilter.GaussianBlur(radius=5))

    overlay = Image.new("RGBA", (canvas_w, canvas_h), (26, 45, 90, 200))
    img = photo.convert("RGBA")
    img.paste(overlay, (0, 0), overlay)
    img = img.convert("RGB")

    draw = ImageDraw.Draw(img)
    draw_accent_line(draw, SAFE + 40, SAFE + 180, length=110, thickness=10, fill=RED)
    _draw_sp_text_block(draw, content, SAFE + 240, canvas_w, canvas_h, text_color=WHITE)

    return draw_logo_pill(img, dark_bg=True)


# ============================================================================
# LAYOUTS REGISTRY
# ============================================================================

LAYOUTS = {
    # Carousel
    "L1": render_L1,
    "L2": render_L2,
    "L3": render_L3,
    "L4": render_L4,
    "L5": render_L5,
    # Single post — graphic
    "S1": render_S1,
    "S2": render_S2,
    "S3": render_S3,
    "S4": render_S4,
    # Single post — photo-based
    "SP4": render_SP4,
    "SP5": render_SP5,
    "SP1": render_SP1,
    "SP2": render_SP2,
    "SP3": render_SP3,
}

# ============================================================================
# MAIN
# ============================================================================

def render_one(layout_name, content, output_path):
    if layout_name not in LAYOUTS:
        raise ValueError(f"Unknown layout: {layout_name}. Available: {list(LAYOUTS.keys())}")
    img = LAYOUTS[layout_name](content)
    # Downscale output if OUTPUT_SCALE < 1.0 (render at 1800px for quality, export smaller)
    if OUTPUT_SCALE != 1.0:
        new_w = int(img.width * OUTPUT_SCALE)
        new_h = int(img.height * OUTPUT_SCALE)
        img = img.resize((new_w, new_h), Image.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)
    print(f"[ok] {layout_name} -> {output_path}  ({img.width}×{img.height}px)")


def write_caption_files(cfg, out_dir, slides):
    """Auto-export caption.md (formatted) + caption.txt (raw copy-paste).
    Signature contact (BRAND_SIGNATURE) is appended after the caption body."""
    caption = cfg.get("caption", "")
    hashtags = cfg.get("hashtags", [])
    topic = cfg.get("topic", "carousel")
    # Allow per-config override; default to global BRAND_SIGNATURE.
    signature = cfg.get("signature", BRAND_SIGNATURE)

    if not caption and not hashtags and not signature:
        return  # nothing to write
    out_dir.mkdir(parents=True, exist_ok=True)

    hashtag_line = " ".join(h if h.startswith("#") else f"#{h}" for h in hashtags)

    # Compose final caption body with signature appended (blank line separator)
    full_caption_parts = []
    if caption:
        full_caption_parts.append(caption.rstrip())
    if signature:
        full_caption_parts.append(signature.rstrip())
    full_caption = "\n\n".join(full_caption_parts)

    # caption.txt — raw copy-paste version (caption + signature + hashtags)
    txt_lines = [full_caption] if full_caption else []
    if hashtag_line:
        txt_lines.append("")
        txt_lines.append(hashtag_line)
    (out_dir / "caption.txt").write_text("\n".join(txt_lines), encoding="utf-8")

    # caption.md — formatted reference with slide map
    md = [f"# Caption — {topic}", ""]
    md += ["## Caption (copy-paste vào Facebook/TikTok)", "", "```", full_caption, "```", ""]
    if hashtag_line:
        md += ["## Hashtags", "", "```", hashtag_line, "```", ""]

    # Slide reference map — which file = which slide
    md += ["## Slide order (đăng kèm)", ""]
    for i, slide in enumerate(slides, start=1):
        layout = slide["layout"]
        content = slide.get("content", {})
        # Best-effort headline extraction
        head = (
            content.get("headline")
            or content.get("headline_top")
            or content.get("sub_hook")
            or "—"
        )
        head = head.replace("\n", " ").strip()
        md.append(f"- **slide_{i}_{layout}.png** — {head}")
    md.append("")
    (out_dir / "caption.md").write_text("\n".join(md), encoding="utf-8")

    print(f"[ok] caption -> {out_dir / 'caption.md'} + caption.txt")


def render_carousel(config_path):
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    topic = cfg.get("topic", "carousel")
    out_dir_str = cfg.get("output_dir", f"output/{topic}")
    out_dir = Path(out_dir_str)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    slides = cfg.get("slides", [])
    print(f"Composing {len(slides)} slides for: {topic}\n")
    for i, slide in enumerate(slides, start=1):
        layout = slide["layout"]
        content = slide.get("content", {})
        out_path = out_dir / f"slide_{i}_{layout}.png"
        render_one(layout, content, out_path)
    write_caption_files(cfg, out_dir, slides)
    print(f"\nDone. Output folder: {out_dir}")


def main():
    parser = argparse.ArgumentParser(description="Akano slide composer")
    parser.add_argument("--carousel", type=str, help="Path to carousel JSON config")
    parser.add_argument("--layout", choices=list(LAYOUTS.keys()), help="Layout for single slide")
    parser.add_argument("--headline", type=str, help="Headline text (single slide mode)")
    parser.add_argument("--out", type=str, default="output/slide.png", help="Output path (single slide)")
    args = parser.parse_args()

    if args.carousel:
        render_carousel(args.carousel)
    elif args.layout:
        content = {"headline": args.headline} if args.headline else {}
        render_one(args.layout, content, ROOT / args.out)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
