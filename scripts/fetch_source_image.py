#!/usr/bin/env python3
"""從文章的 source_url 抓主圖，存成跟文章同名的 webp，並寫入 image_credit。

只改 front matter 的 image 與 image_credit，不改內文。
找不到可用照片時保留原圖，image_credit 設為「示意圖（AI 生成）」，結束碼仍是 0。
"""

from __future__ import annotations

import io
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site  # noqa: E402

MIN_WIDTH = 400
BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
GENERIC_URL = re.compile(
    r"(pic_fb|favicon|sprite|1x1|pixel|spacer|blank\.|placeholder|no-?image|"
    r"og[-_]default|default[-_]og|/logo|logo\.|icon|avatar|/ads?/|advert|"
    r"appstore|googleplay|line-ad|line\.png|fb\.png|share\.png|emoji)",
    re.I,
)
META_PATTERNS = (
    re.compile(r"""<meta[^>]+property=["']og:image(?::secure_url)?["'][^>]+content=["']([^"']+)["']""", re.I),
    re.compile(r"""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image(?::secure_url)?["']""", re.I),
    re.compile(r"""<meta[^>]+name=["']twitter:image(?::src)?["'][^>]+content=["']([^"']+)["']""", re.I),
    re.compile(r"""<meta[^>]+content=["']([^"']+)["'][^>]+name=["']twitter:image(?::src)?["']""", re.I),
)
IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
SRC_ATTR = re.compile(r"""(?:data-src|src)=["']([^"']+)["']""", re.I)
STOP_MARKERS = ("推薦新聞", "延伸閱讀", "相關新聞", "更多新聞", "你可能也想看", "<footer", "article-feed")
AI_CREDIT = "示意圖（AI 生成）"


def is_generic_url(url: str) -> bool:
    path = urllib.parse.urlparse(url).path
    return bool(GENERIC_URL.search(path) or GENERIC_URL.search(url))


def absolutize(url: str, base: str) -> str:
    url = (url or "").strip()
    if not url or url.startswith("data:"):
        return ""
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith(("http://", "https://")):
        url = urllib.parse.urljoin(base, url)
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url


def is_google_news(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host.startswith("news.google.")


def fetch_html(url: str, timeout: float = 20) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.5",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final = response.geturl()
        raw = response.read(1_500_000)
    return raw.decode("utf-8", "replace"), final


def publisher_url(page: str, base: str) -> str:
    patterns = (
        r"""<meta[^>]+property=["']og:url["'][^>]+content=["']([^"']+)["']""",
        r"""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:url["']""",
        r"""<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)["']""",
        r"""<link[^>]+href=["']([^"']+)["'][^>]+rel=["']canonical["']""",
    )
    for pattern in patterns:
        match = re.search(pattern, page, re.I)
        if not match:
            continue
        found = absolutize(match.group(1), base)
        if found.startswith("https://") and not is_google_news(found):
            return found
    return ""


def meta_images(page: str, base: str) -> list[str]:
    found = []
    for pattern in META_PATTERNS:
        for match in pattern.finditer(page):
            url = absolutize(match.group(1), base)
            if url.startswith("https://") and url not in found:
                found.append(url)
    return found


def article_region(page: str) -> str:
    start = len(page)
    for marker in ("itemprop=\"articleBody\"", "itemprop='articleBody'", 'class="article"', "<article"):
        index = page.find(marker)
        if index != -1:
            start = min(start, index)
    if start == len(page):
        start = 0
    region = page[start:]
    stop = len(region)
    for marker in STOP_MARKERS:
        index = region.find(marker)
        if index > 0:
            stop = min(stop, index)
    return region[:stop]


def article_images(page: str, base: str) -> list[str]:
    found = []
    for tag in IMG_TAG.findall(article_region(page)):
        match = SRC_ATTR.search(tag)
        if not match:
            continue
        url = absolutize(match.group(1), base)
        if not url.startswith("https://") or url in found:
            continue
        if not re.search(r"\.(jpe?g|png|webp)(\?|$)", urllib.parse.urlparse(url).path, re.I):
            continue
        found.append(url)
    return found


def download_image(url: str, referer: str):
    from PIL import Image
    request = urllib.request.Request(
        url,
        headers={"User-Agent": BROWSER, "Accept": "image/avif,image/webp,image/*,*/*", "Referer": referer},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(8_000_000)
            kind = (response.headers.get("content-type") or "").lower()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if kind and "image" not in kind and "octet-stream" not in kind:
        return None
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        return None
    if image.width < MIN_WIDTH or image.height < 80:
        return None
    return image


def to_rgb(image):
    from PIL import Image
    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA"}:
        base = Image.new("RGB", image.size, (255, 255, 255))
        base.paste(image, mask=image.getchannel("A"))
        return base
    return image.convert("RGB")


def candidate_urls(page: str, base: str) -> list[str]:
    urls = []
    for url in meta_images(page, base) + article_images(page, base):
        if is_generic_url(url) or url in urls:
            continue
        urls.append(url)
    return urls


def resolve_page(url: str) -> tuple[str, str]:
    page, final = fetch_html(url)
    if is_google_news(final):
        publisher = publisher_url(page, final)
        if publisher:
            page, final = fetch_html(publisher)
    return page, final


def quote_value(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def update_front_matter(text: str, image_name: str, credit: str) -> str:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError("文章沒有 front matter")
    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise ValueError("找不到 front matter 結尾")
    raw = normalized[4:end]
    body = normalized[end + 5 :]
    lines = raw.split("\n")
    new_lines = []
    saw_credit = False
    for line in lines:
        key = line.split(":", 1)[0].strip() if ":" in line and not line.startswith((" ", "\t", "-")) else ""
        if key == "image":
            new_lines.append(f"image: {quote_value(image_name)}")
            continue
        if key == "image_credit":
            new_lines.append(f"image_credit: {quote_value(credit)}")
            saw_credit = True
            continue
        new_lines.append(line)
    if not saw_credit:
        inserted = []
        placed = False
        for line in new_lines:
            inserted.append(line)
            if not placed and line.startswith("image:"):
                inserted.append(f"image_credit: {quote_value(credit)}")
                placed = True
        new_lines = inserted
    return "---\n" + "\n".join(new_lines).strip("\n") + "\n---\n" + body


def apply(post_path: Path) -> int:
    original = post_path.read_text(encoding="utf-8")
    meta, _body = build_site.parse_front_matter(original)
    source = meta.get("source_url", "")
    source_name = meta.get("source_name", "").strip() or "原媒體"
    image_name = f"{post_path.stem}.webp"
    target = post_path.parent / image_name
    chosen = None
    chosen_url = ""
    try:
        page, final = resolve_page(source)
        for url in candidate_urls(page, final):
            image = download_image(url, final)
            if image is None:
                print(f"[略過] {url} 太小或不是照片")
                continue
            chosen = image
            chosen_url = url
            break
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        print(f"[略過] 無法讀取原文：{error}")
    if chosen is None:
        if not target.is_file():
            raise SystemExit(f"沒有可用照片，也找不到原圖：{target}")
        post_path.write_text(update_front_matter(original, image_name, AI_CREDIT), encoding="utf-8")
        print(f"[示意圖] {post_path.name} 保留 {image_name}")
        return 0
    from PIL import Image

    rgb = to_rgb(chosen)
    if rgb.width > 1600:
        height = round(rgb.height * 1600 / rgb.width)
        rgb = rgb.resize((1600, height), Image.Resampling.LANCZOS)
    rgb.save(target, "WEBP", quality=82, method=6)
    post_path.write_text(update_front_matter(original, image_name, f"圖片來源：{source_name}"), encoding="utf-8")
    print(f"[照片] {post_path.name} {rgb.width}x{rgb.height} {chosen_url}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("用法：python3 scripts/fetch_source_image.py posts/YYYY-MM-DD/NN-slug.md")
    path = Path(args[0])
    if not path.is_file():
        raise SystemExit(f"找不到文章：{path}")
    return apply(path)


if __name__ == "__main__":
    sys.exit(main())
