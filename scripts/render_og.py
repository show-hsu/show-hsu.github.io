#!/usr/bin/env python3
"""重畫分享用圖片。網站每天更新時不會跑這支，只在要換圖時手動執行。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"


def main() -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as error:
        raise SystemExit("需要 Pillow 才能重畫圖片。日常產生日報不需要它。") from error

    image = Image.new("RGB", (1200, 630), "#102e2b")
    draw = ImageDraw.Draw(image)
    draw.ellipse((1020, -120, 1380, 240), fill="#164840")
    draw.rectangle((0, 548, 1200, 630), fill="#c6a15b")
    draw.rectangle((72, 150, 160, 158), fill="#c6a15b")
    draw.rounded_rectangle((780, 400, 836, 520), radius=10, fill="#8ed0c3")
    draw.rounded_rectangle((856, 330, 912, 520), radius=10, fill="#e7d3a1")
    draw.rounded_rectangle((932, 250, 988, 520), radius=10, fill="#f6f3ec")
    title_font = ImageFont.truetype(FONT, 68, index=0)
    sub_font = ImageFont.truetype(FONT, 32, index=0)
    small_font = ImageFont.truetype(FONT, 26, index=0)
    draw.text((72, 64), "SHOW", font=small_font, fill="#c6a15b")
    draw.text((72, 180), "金融保險理財日報", font=title_font, fill="#f6f3ec")
    draw.text((72, 280), "保險 · 理財 · 利率 · 退休", font=sub_font, fill="#d5e4df")
    draw.text((72, 572), "show-hsu.github.io", font=small_font, fill="#102e2b")
    image.save(ROOT / "assets" / "og.png", "PNG", optimize=True)

    icon = Image.new("RGB", (180, 180), "#102e2b")
    icon_draw = ImageDraw.Draw(icon)
    icon_draw.rectangle((0, 146, 180, 180), fill="#c6a15b")
    icon_font = ImageFont.truetype(FONT, 96, index=0)
    icon_draw.text((48, 28), "S", font=icon_font, fill="#f6f3ec")
    icon.save(ROOT / "assets" / "apple-touch-icon.png", "PNG", optimize=True)


if __name__ == "__main__":
    main()
