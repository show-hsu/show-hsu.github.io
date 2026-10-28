#!/usr/bin/env python3
"""用 assets/logo.png 重畫分享圖。日常發布不會跑這支。"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SERIF = ROOT / "assets" / "fonts" / "NotoSerifTC-600.ttf"
SANS = Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")


def main() -> None:
    logo = Image.open(ROOT / "assets" / "logo.png").convert("RGBA")
    image = Image.new("RGB", (1200, 630), "#f6f2ec")
    mark = logo.resize((440, 440), Image.Resampling.LANCZOS)
    image.paste(mark, (64, 60), mark)
    draw = ImageDraw.Draw(image)
    title = ImageFont.truetype(SERIF, 64)
    sub = ImageFont.truetype(SERIF, 28)
    host = ImageFont.truetype(SANS, 26)
    draw.rectangle((560, 196, 632, 198), fill="#a5865a")
    draw.text((560, 220), "藝世錄", font=title, fill="#1d1b19")
    draw.text((560, 304), "金融理財日報", font=title, fill="#1d1b19")
    draw.text((560, 408), "保險 · 理財 · 利率 · 退休", font=sub, fill="#6e5638")
    draw.rectangle((0, 560, 1200, 630), fill="#a5865a")
    draw.text((72, 580), "yishilu-daily.github.io", font=host, fill="#1d1b19")
    image.save(ROOT / "assets" / "og.png", "PNG", optimize=True)


if __name__ == "__main__":
    main()
