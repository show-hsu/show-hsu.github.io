#!/usr/bin/env python3
"""用 assets/logo.png 重畫分享圖與方形圖示。日常發布不會跑這支。"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"


def main() -> None:
    logo = Image.open(ROOT / "assets" / "logo.png").convert("RGBA")
    image = Image.new("RGB", (1200, 630), "#1c1c1c")
    mark = logo.resize((470, 470), Image.Resampling.LANCZOS)
    image.paste(mark, (48, 70), mark)
    draw = ImageDraw.Draw(image)
    title = ImageFont.truetype(FONT, 64, index=0)
    sub = ImageFont.truetype(FONT, 28, index=0)
    draw.rectangle((560, 210, 680, 218), fill="#d4b36a")
    draw.text((560, 240), "藝世錄", font=title, fill="#f6f3ec")
    draw.text((560, 320), "金融理財日報", font=title, fill="#f6f3ec")
    draw.text((560, 420), "保險 · 理財 · 利率 · 退休", font=sub, fill="#d4b36a")
    draw.rectangle((0, 560, 1200, 630), fill="#d4b36a")
    draw.text((72, 578), "show-hsu.github.io", font=sub, fill="#1c1c1c")
    image.save(ROOT / "assets" / "og.png", "PNG", optimize=True)


if __name__ == "__main__":
    main()
