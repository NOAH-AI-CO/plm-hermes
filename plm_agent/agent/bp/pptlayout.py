import os
import asyncio
import re
from PIL import Image, ImageDraw, ImageFont


# 拼接出 gcp_key.json 的绝对路径
gcp_key_path = "/Users/andy/repos/NoahAgent/noah_agent/gcp_key.json"
if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', ''):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

os.environ['GOOGLE_CLOUD_PROJECT'] = "noahai-440408"
os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"

import pymupdf

from google import genai
from google.genai.types import HttpOptions
import json
        
client = genai.Client(http_options=HttpOptions(api_version="v1"))

async def llm_translate(text, target_language='Chinese'):
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=f"Help me translate the following text to {target_language}, maintaining formatting if possible, only return the translation result:\n\n" + text,
        config={
            "temperature": 0,
        },
    )
    return response.text


# ─────────────────────────────────────────────────────────────────────────────
# Layout design constants
# ─────────────────────────────────────────────────────────────────────────────

_FILL_COLORS: dict[str, tuple] = {
    "title":     (255, 210, 100, 180),   # warm amber
    "paragraph": (173, 216, 230, 160),   # light blue
    "image":     (144, 238, 144, 160),   # light green
}
_BORDER_COLORS: dict[str, tuple] = {
    "title":     (180, 120,   0),
    "paragraph": ( 60, 110, 170),
    "image":     ( 30, 130,  30),
}
_LABEL_COLORS: dict[str, tuple] = {
    "title":     ( 80,  50,   0),
    "paragraph": ( 20,  60, 120),
    "image":     ( 10,  80,  10),
}


async def llm_design_layout(
    n_images: int = 2,
    n_paragraphs: int = 3,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
    model: str = "gemini-3-flash-preview",
) -> list[dict]:
    """
    Ask a Gemini LLM to produce pixel-perfect block coordinates for a slide
    containing a title, ``n_paragraphs`` text blocks, and ``n_images`` image
    blocks on a ``canvas_width`` × ``canvas_height`` canvas.

    Returns a list of dicts, each with keys:
        id, type, label, x, y, width, height
    """
    prompt = f"""You are an expert presentation slide layout designer.

Design a **tight, non-overlapping** layout for a {canvas_width}×{canvas_height} px slide
that contains exactly these elements:

  • 1  title block  (spans full width, 80–100 px tall, at the very top)
  • {n_paragraphs}  paragraph blocks  (large bodies of text)
  • {n_images}  image blocks  (roughly 16:9 or 4:3 aspect ratio)

Hard constraints
────────────────
• Canvas boundary: every block must satisfy  x≥20, y≥20,
  x+width≤{canvas_width-20}, y+height≤{canvas_height-20}.
• No two blocks may overlap (even by 1 px).
• Gap between any two adjacent blocks: 15–25 px.
• Title is always the topmost element.
• Fill the canvas as fully as possible — minimal wasted white space.

Layout suggestions
──────────────────
• After the title use a 2- or 3-column grid for the remaining elements.
• Place images where they visually balance the paragraphs.
• Paragraphs should be at least 200 px tall.
• Images should preserve a natural aspect ratio (roughly 400×280 or similar).

Output format
─────────────
Return ONLY a valid JSON array — no markdown fences, no explanation.
Each element in the array must have exactly these keys:
  "id"     : unique snake_case identifier  (title | para_1 | para_2 | para_3 | img_1 | img_2 …)
  "type"   : one of  title | paragraph | image
  "label"  : human-readable label  ("Title", "Paragraph 1", "Image 1" …)
  "x"      : integer  (left edge, px)
  "y"      : integer  (top edge, px)
  "width"  : integer  (px)
  "height" : integer  (px)
"""

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={"temperature": 0.2},
    )

    raw = response.text.strip()
    # Strip any accidental markdown code fences
    raw = re.sub(r"^```[a-z]*\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    blocks: list[dict] = json.loads(raw)
    return blocks


def _try_load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try to load a decent system font; fall back to PIL default."""
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_layout_preview(
    blocks: list[dict],
    canvas_width: int = 1920,
    canvas_height: int = 1080,
    output_path: str = "layout_preview.png",
    scale: float = 0.6,
) -> str:
    """
    Render coloured labelled rectangles for each block onto a canvas and save
    as a PNG.  Returns the output path.

    Parameters
    ----------
    blocks      : list of block dicts returned by ``llm_design_layout``
    canvas_width / canvas_height : slide dimensions in pixels
    output_path : where to write the PNG
    scale       : downsample factor for the saved image (e.g. 0.5 → half size)
    """
    img  = Image.new("RGBA", (canvas_width, canvas_height), (245, 245, 248, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    font_title = _try_load_font(48)
    font_label = _try_load_font(36)
    font_dim   = _try_load_font(26)

    # Faint grid lines for reference
    for gx in range(0, canvas_width, 120):
        draw.line([(gx, 0), (gx, canvas_height)], fill=(210, 210, 220, 120), width=1)
    for gy in range(0, canvas_height, 120):
        draw.line([(0, gy), (canvas_width, gy)], fill=(210, 210, 220, 120), width=1)

    for block in blocks:
        btype  = block.get("type", "paragraph")
        bid    = block.get("id",    "?")
        label  = block.get("label", bid)
        x      = int(block["x"])
        y      = int(block["y"])
        w      = int(block["width"])
        h      = int(block["height"])

        fill   = _FILL_COLORS.get(btype,   (200, 200, 200, 160))
        border = _BORDER_COLORS.get(btype, (100, 100, 100))
        tcolor = _LABEL_COLORS.get(btype,  ( 30,  30,  30))

        # Filled rectangle with rounded-ish border
        draw.rectangle([x, y, x + w, y + h], fill=fill, outline=border, width=5)

        # ── inner shadow (top-left lighter, bottom-right darker) ──────────
        draw.line([(x+5, y+5), (x+w-5, y+5)],    fill=(255,255,255,80), width=3)
        draw.line([(x+5, y+5), (x+5,   y+h-5)],  fill=(255,255,255,80), width=3)

        # ── type badge (top-left corner) ─────────────────────────────────
        badge_text  = btype.upper()
        badge_bbox  = draw.textbbox((0, 0), badge_text, font=font_dim)
        badge_w     = badge_bbox[2] - badge_bbox[0] + 20
        badge_h     = badge_bbox[3] - badge_bbox[1] + 10
        draw.rectangle([x+8, y+8, x+8+badge_w, y+8+badge_h],
                       fill=(*border, 200), outline=None)
        draw.text((x+18, y+13), badge_text, fill=(255, 255, 255), font=font_dim)

        # ── centred label ────────────────────────────────────────────────
        main_font  = font_title if btype == "title" else font_label
        dim_text   = f"{w} × {h} px"

        # Two-line centred: label + dimensions
        lbbox = draw.textbbox((0, 0), label,    font=main_font)
        dbbox = draw.textbbox((0, 0), dim_text, font=font_dim)
        lw, lh = lbbox[2] - lbbox[0], lbbox[3] - lbbox[1]
        dw, dh = dbbox[2] - dbbox[0], dbbox[3] - dbbox[1]

        gap      = 10
        total_h  = lh + gap + dh
        ly       = y + (h - total_h) // 2
        dy       = ly + lh + gap

        draw.text((x + (w - lw) // 2, ly), label,    fill=tcolor, font=main_font)
        draw.text((x + (w - dw) // 2, dy), dim_text, fill=tcolor, font=font_dim)

    # Convert to RGB before saving (JPEG/PNG compat)
    img_rgb = img.convert("RGB")

    if scale != 1.0:
        new_w = int(canvas_width  * scale)
        new_h = int(canvas_height * scale)
        img_rgb = img_rgb.resize((new_w, new_h), Image.LANCZOS)

    img_rgb.save(output_path)
    print(f"✅  Layout preview saved → {output_path}  "
          f"({img_rgb.width}×{img_rgb.height} px)")
    return output_path


async def demo_layout(output_path: str = "layout_preview.png") -> str:
    """
    End-to-end demo: ask the LLM to design a layout for 2 images + 3 paragraphs
    + 1 title on a 1920×1080 canvas, then render and save the result.
    """
    print("🎨  Requesting layout from LLM …")
    blocks = await llm_design_layout(n_images=3, n_paragraphs=2)

    print(f"\n📐  Received {len(blocks)} blocks:")
    print(f"  {'id':<14} {'type':<12} {'x':>5} {'y':>5} {'w':>6} {'h':>6}  label")
    print("  " + "─" * 65)
    for b in blocks:
        print(f"  {b['id']:<14} {b['type']:<12} "
              f"{b['x']:>5} {b['y']:>5} {b['width']:>6} {b['height']:>6}  {b['label']}")

    path = draw_layout_preview(blocks, output_path=output_path)
    return path


if __name__ == "__main__":
    asyncio.run(demo_layout())
