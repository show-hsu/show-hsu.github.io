#!/usr/bin/env python3
"""把 posts/ 裡的專欄渲染成靜態頁。不抓 RSS，也不會改 posts/。"""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POST_NAME = re.compile(r"^(\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)$")
WEEKDAYS = "一二三四五六日"
REQUIRED = ("title", "date", "category", "summary", "image", "source_name", "source_url")


def esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def site_config(root: Path) -> dict:
    settings = json.loads((root / "config" / "settings.json").read_text(encoding="utf-8"))
    return {
        "site_url": settings["site_url"].rstrip("/"),
        "site_name": settings["site_name"],
        "owner_name": settings.get("owner_name") or "許欣霈",
        "timezone": settings.get("timezone") or "Asia/Taipei",
    }


def parse_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_front_matter(text: str) -> tuple[dict, str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError("文章必須以 --- 開頭的 front matter 開始")
    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise ValueError("找不到 front matter 的結尾 ---")
    raw = normalized[4:end]
    body = normalized[end + 5 :]
    data: dict = {}
    tags: list[str] | None = None
    collecting_tags = False
    for line in raw.splitlines():
        if not line.strip():
            continue
        if collecting_tags and re.match(r"^\s+-\s+", line):
            tags.append(parse_scalar(line.split("-", 1)[1]))
            continue
        collecting_tags = False
        if ":" not in line:
            raise ValueError(f"無法讀取 front matter：{line}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key == "tags" and value in {"", "[]"}:
            tags = []
            collecting_tags = value == ""
            data["tags"] = tags
            continue
        if key == "tags" and value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data["tags"] = [parse_scalar(part) for part in inner.split(",") if part.strip()]
            continue
        data[key] = parse_scalar(value)
    data.setdefault("tags", [])
    return data, body.lstrip("\n")


def inline_markdown(text: str) -> str:
    escaped = esc(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)

    def link(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        if not url.startswith(("https://", "http://")):
            return label
        return f'<a href="{esc(url)}">{label}</a>'

    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", link, escaped)


def render_markdown(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_kind = ""
    quote: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append("<p>" + inline_markdown(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_kind
        if list_items:
            tag = "ol" if list_kind == "ol" else "ul"
            blocks.append(f"<{tag}>" + "".join(f"<li>{inline_markdown(item)}</li>" for item in list_items) + f"</{tag}>")
            list_items.clear()
            list_kind = ""

    def flush_quote() -> None:
        if quote:
            blocks.append("<blockquote><p>" + inline_markdown(" ".join(quote)) + "</p></blockquote>")
            quote.clear()

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph()
            flush_list()
            flush_quote()
            continue
        if line.strip() == "---":
            flush_paragraph()
            flush_list()
            flush_quote()
            blocks.append("<hr>")
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            flush_quote()
            level = len(heading.group(1)) + 1
            level = min(level, 4)
            blocks.append(f"<h{level}>{inline_markdown(heading.group(2))}</h{level}>")
            continue
        if line.startswith("> "):
            flush_paragraph()
            flush_list()
            quote.append(line[2:].strip())
            continue
        unordered = re.match(r"^[-*]\s+(.+)$", line)
        ordered = re.match(r"^\d+\.\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            flush_quote()
            kind = "ul" if unordered else "ol"
            if list_kind and list_kind != kind:
                flush_list()
            list_kind = kind
            list_items.append((unordered or ordered).group(1).strip())
            continue
        flush_list()
        flush_quote()
        paragraph.append(line.strip())
    flush_paragraph()
    flush_list()
    flush_quote()
    return "\n".join(blocks)


def format_date(day: str) -> str:
    year, month, date = (int(part) for part in day.split("-"))
    return f"{year}年{month}月{date}日"


def weekday_label(day: str) -> str:
    moment = datetime.fromisoformat(day)
    return "星期" + WEEKDAYS[moment.weekday()]


def load_posts(root: Path) -> list[dict]:
    folder = root / "posts"
    if not folder.exists():
        return []
    posts = []
    for path in sorted(folder.glob("*/*.md")):
        day = path.parent.name
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise SystemExit(f"日期資料夾名稱不對：{path.parent}")
        match = POST_NAME.fullmatch(path.stem)
        if not match:
            raise SystemExit(f"檔名須為 NN-slug.md，例如 01-claim-age.md：{path.name}")
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        missing = [key for key in REQUIRED if not str(meta.get(key, "")).strip()]
        if missing:
            raise SystemExit(f"{path} 缺少欄位：{', '.join(missing)}")
        if meta["date"] != day:
            raise SystemExit(f"{path} 的 date 必須等於資料夾日期 {day}")
        image_name = meta["image"]
        if not re.fullmatch(r"[\w.-]+\.(webp|png)", image_name) or Path(image_name).stem != path.stem:
            raise SystemExit(f"{path} 的 image 必須是同名的 .webp 或 .png")
        image_path = path.parent / image_name
        if not image_path.is_file():
            raise SystemExit(f"找不到圖片：{image_path}")
        if not str(meta["source_url"]).startswith(("https://", "http://")):
            raise SystemExit(f"{path} 的 source_url 必須是 http(s) 連結")
        order = int(match.group(1))
        slug = path.stem
        posts.append(
            {
                "order": order,
                "slug": slug,
                "date": day,
                "title": meta["title"].strip(),
                "category": meta["category"].strip(),
                "summary": meta["summary"].strip(),
                "image": image_name,
                "image_url": f"/posts/{day}/{image_name}",
                "source_name": meta["source_name"].strip(),
                "source_url": meta["source_url"].strip(),
                "image_credit": str(meta.get("image_credit") or "").strip(),
                "tags": list(meta.get("tags") or []),
                "body": body.strip(),
                "html": render_markdown(body),
                "path": path,
            }
        )
    posts.sort(key=lambda post: (post["date"], post["order"], post["slug"]), reverse=True)
    return posts


def prose_to_html(text: str) -> str:
    stripped = re.sub(r"<!--.*?-->", "", text or "", flags=re.S).strip()
    if not stripped:
        return ""
    return render_markdown(stripped)


def apply_template(template: str, mapping: dict[str, str]) -> str:
    page = template
    for key, value in mapping.items():
        page = page.replace(f"@@{key}@@", value)
    leftover = re.findall(r"@@[A-Z_]+@@", page)
    if leftover:
        raise RuntimeError(f"模板還有未替換的標記：{', '.join(leftover)}")
    return page


def json_ld(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def page(template: str, settings: dict, *, title: str, description: str, canonical: str, image: str, main: str, current: str, og_type: str = "website") -> str:
    nav = {"TODAY": "", "ARCHIVE": "", "ABOUT": ""}
    if current in nav:
        nav[current] = 'aria-current="page"'
    year = str(datetime.now().year)
    return apply_template(
        template,
        {
            "TITLE": esc(title),
            "DESCRIPTION": esc(description),
            "CANONICAL": esc(canonical),
            "OG_TYPE": esc(og_type),
            "OG_TITLE": esc(title),
            "OG_IMAGE": esc(image),
            "OG_IMAGE_ALT": esc(title),
            "EXTRA_HEAD": "",
            "JSONLD": json_ld(
                {
                    "@context": "https://schema.org",
                    "@type": "Article" if og_type == "article" else "WebPage",
                    ("headline" if og_type == "article" else "name"): title,
                    "url": canonical,
                    "description": description,
                    "image": image,
                    "inLanguage": "zh-Hant",
                    "author": {"@type": "Person", "name": settings["owner_name"]},
                }
            ),
            "NAV_TODAY": nav["TODAY"],
            "NAV_ARCHIVE": nav["ARCHIVE"],
            "NAV_ABOUT": nav["ABOUT"],
            "MAIN": main,
            "YEAR": year,
        },
    )


def absolute_image(settings: dict, image_url: str) -> str:
    if image_url.startswith("http"):
        return image_url
    return settings["site_url"] + image_url


def card(post: dict, *, eager: bool) -> str:
    loading = 'fetchpriority="high"' if eager else 'loading="lazy" decoding="async"'
    flag = ""
    if "範例" in post["tags"]:
        flag = '<p class="sample-flag">範例，可替換</p>'
    credit = ""
    if post.get("image_credit"):
        credit = f'<span class="image-credit">{esc(post["image_credit"])}</span>'
    return (
        f'<a class="feature-card" href="/column/{esc(post["date"])}/{esc(post["slug"])}/">'
        '<span class="feature-media">'
        f'<img src="{esc(post["image_url"])}" alt="" width="1200" height="675" {loading}>'
        f"{credit}</span>"
        '<span class="feature-body">'
        f'<p class="kicker">{esc(post["category"])}</p>'
        f'<h2>{esc(post["title"])}</h2>'
        f'<p class="summary">{esc(post["summary"])}</p>'
        f'<p class="meta"><time datetime="{esc(post["date"])}">{esc(format_date(post["date"]))}</time></p>'
        f"{flag}</span></a>"
    )


def render_home(posts: list[dict], about_html: str) -> str:
    if not posts:
        return (
            '<article class="day-lead"><p class="kicker">專欄</p>'
            "<h1>Show 的金融保險理財日報</h1>"
            '<p class="lead">還沒有文章。新的一篇放進 posts/ 之後就會出現在這裡。</p></article>'
        )
    latest = posts[0]["date"]
    today = [post for post in posts if post["date"] == latest]
    today.sort(key=lambda post: post["order"])
    cards = "".join(card(post, eager=index == 0) for index, post in enumerate(today))
    older_dates = []
    for post in posts:
        if post["date"] != latest and post["date"] not in older_dates:
            older_dates.append(post["date"])
    recent = ""
    if older_dates:
        rows = []
        for day in older_dates:
            count = sum(1 for post in posts if post["date"] == day)
            rows.append(
                f'<li><a href="/archive/{esc(day)}/"><time datetime="{esc(day)}">{esc(format_date(day))}</time>'
                f'<span>{weekday_label(day)} · {count} 篇</span></a></li>'
            )
        recent = '<section class="recent"><h2>近期</h2><ol class="archive-list">' + "".join(rows) + "</ol></section>"
    about = ""
    if about_html:
        about = f'<section class="about" id="about"><h2>關於 Show</h2><div class="prose">{about_html}</div></section>'
    return (
        '<article class="day-lead">'
        f'<p class="kicker">{esc(format_date(latest))} · {weekday_label(latest)}</p>'
        "<h1>今天的專欄</h1>"
        '<p class="lead">挑幾則和保險、理財有關的新聞，用我的話寫給你看。</p>'
        f'<div class="feature-list">{cards}</div>'
        "</article>"
        f"{recent}{about}"
    )


def render_article(post: dict) -> str:
    flag = ""
    if "範例" in post["tags"]:
        flag = '<p class="sample-flag">這是範例文章，正式專欄會整組替換。</p>'
    credit = ""
    if post.get("image_credit"):
        credit = f'<figcaption class="image-credit">{esc(post["image_credit"])}</figcaption>'
    figure = (
        '<figure class="article-figure">'
        f'<img class="article-cover" src="{esc(post["image_url"])}" alt="{esc(post["title"])}" width="1200" height="675">'
        f"{credit}</figure>"
    )
    return (
        "<article>"
        f"{figure}"
        f'<p class="kicker">{esc(post["category"])}</p>'
        f'<h1>{esc(post["title"])}</h1>'
        f'<p class="edition-meta"><time datetime="{esc(post["date"])}">{esc(format_date(post["date"]))}</time> · {weekday_label(post["date"])}</p>'
        f"{flag}<div class=\"prose\">{post['html']}</div>"
        '<section class="source-box"><h2>新聞來源</h2>'
        f'<p><a href="{esc(post["source_url"])}" target="_blank" rel="noopener noreferrer">{esc(post["source_name"])}</a></p>'
        "</section></article>"
    )


def render_archive(posts: list[dict]) -> str:
    dates = []
    for post in posts:
        if post["date"] not in dates:
            dates.append(post["date"])
    rows = []
    for day in dates:
        count = sum(1 for post in posts if post["date"] == day)
        rows.append(
            f'<li><a href="/archive/{esc(day)}/"><time datetime="{esc(day)}">{esc(format_date(day))}</time>'
            f'<span>{weekday_label(day)} · {count} 篇</span></a></li>'
        )
    body = "".join(rows) or '<p class="empty">還沒有文章。</p>'
    return (
        '<article class="archive-block"><p class="kicker">ARCHIVE</p><h1>專欄彙整</h1>'
        '<p class="lead">每一天的文章都留在這裡。</p>'
        f'<ol class="archive-list">{body}</ol></article>'
    )


def render_day(day: str, posts: list[dict]) -> str:
    chosen = [post for post in posts if post["date"] == day]
    chosen.sort(key=lambda post: post["order"])
    cards = "".join(card(post, eager=index == 0) for index, post in enumerate(chosen))
    dates = sorted({post["date"] for post in posts})
    index = dates.index(day)
    links = []
    if index > 0:
        links.append(f'<a href="/archive/{dates[index - 1]}/">前一天</a>')
    else:
        links.append("<span></span>")
    if index < len(dates) - 1:
        links.append(f'<a href="/archive/{dates[index + 1]}/">後一天</a>')
    else:
        links.append("<span></span>")
    return (
        '<article class="day-lead">'
        f'<p class="kicker">當日專欄</p><h1>{esc(format_date(day))}</h1>'
        f'<p class="edition-meta">{weekday_label(day)} · {len(chosen)} 篇</p>'
        f'<div class="feature-list">{cards}</div>'
        f'<p class="pager">{"".join(links)}</p></article>'
    )


def render_about(about_html: str) -> str:
    return (
        '<article class="about"><p class="kicker">ABOUT</p><h1>關於 Show</h1>'
        f'<div class="prose">{about_html}</div>'
        '<p class="share-row"><a href="/">回到今天的專欄</a></p></article>'
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def remove_stale(root: Path, posts: list[dict]) -> None:
    keep_days = {post["date"] for post in posts}
    keep_slugs = {(post["date"], post["slug"]) for post in posts}
    archive = root / "archive"
    if archive.exists():
        for child in archive.iterdir():
            if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name) and child.name not in keep_days:
                shutil.rmtree(child)
    column = root / "column"
    if column.exists():
        for day_dir in column.iterdir():
            if not day_dir.is_dir():
                continue
            if day_dir.name not in keep_days:
                shutil.rmtree(day_dir)
                continue
            for slug_dir in day_dir.iterdir():
                if slug_dir.is_dir() and (day_dir.name, slug_dir.name) not in keep_slugs:
                    shutil.rmtree(slug_dir)


def build(root: Path) -> list[dict]:
    settings = site_config(root)
    posts = load_posts(root)
    template = (root / "templates" / "layout.html").read_text(encoding="utf-8")
    about_html = prose_to_html((root / "data" / "about.md").read_text(encoding="utf-8")) if (root / "data" / "about.md").exists() else ""
    site = settings["site_url"]
    brand_image = site + "/assets/og.png"
    lead = None
    if posts:
        latest_day = max(post["date"] for post in posts)
        lead = min((post for post in posts if post["date"] == latest_day), key=lambda post: post["order"])
    latest_image = absolute_image(settings, lead["image_url"]) if lead else brand_image
    home_description = lead["summary"] if lead else "Show 的保險與理財專欄。"
    home_title = settings["site_name"]
    if lead:
        home_title = f"{format_date(lead['date'])}｜{settings['site_name']}"
    write_text(
        root / "index.html",
        page(
            template,
            settings,
            title=home_title,
            description=home_description,
            canonical=site + "/",
            image=latest_image,
            main=render_home(posts, about_html),
            current="TODAY",
        ),
    )
    remove_stale(root, posts)
    for day in sorted({post["date"] for post in posts}):
        write_text(
            root / "archive" / day / "index.html",
            page(
                template,
                settings,
                title=f"{format_date(day)}｜{settings['site_name']}",
                description=f"{format_date(day)}的專欄。",
                canonical=f"{site}/archive/{day}/",
                image=absolute_image(settings, next(post["image_url"] for post in posts if post["date"] == day)),
                main=render_day(day, posts),
                current="ARCHIVE",
            ),
        )
    for post in posts:
        canonical = f"{site}/column/{post['date']}/{post['slug']}/"
        write_text(
            root / "column" / post["date"] / post["slug"] / "index.html",
            page(
                template,
                settings,
                title=f"{post['title']}｜{settings['site_name']}",
                description=post["summary"],
                canonical=canonical,
                image=absolute_image(settings, post["image_url"]),
                main=render_article(post),
                current="",
                og_type="article",
            ),
        )
    write_text(
        root / "archive" / "index.html",
        page(
            template,
            settings,
            title=f"專欄彙整｜{settings['site_name']}",
            description="過去每一天的專欄。",
            canonical=site + "/archive/",
            image=brand_image,
            main=render_archive(posts),
            current="ARCHIVE",
        ),
    )
    write_text(
        root / "about" / "index.html",
        page(
            template,
            settings,
            title=f"關於 Show｜{settings['site_name']}",
            description=f"{settings['owner_name']}（Show）的金融保險理財日報。",
            canonical=site + "/about/",
            image=brand_image,
            main=render_about(about_html),
            current="ABOUT",
        ),
    )
    urls = [site + "/", site + "/archive/", site + "/about/"]
    urls.extend(f"{site}/archive/{day}/" for day in sorted({post["date"] for post in posts}))
    urls.extend(f"{site}/column/{post['date']}/{post['slug']}/" for post in posts)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    lines.extend(f"  <url><loc>{esc(url)}</loc></url>" for url in urls)
    lines.append("</urlset>")
    write_text(root / "sitemap.xml", "\n".join(lines) + "\n")
    print(f"完成：{len(posts)} 篇文章")
    for post in sorted(posts, key=lambda item: (item["date"], item["order"])):
        print(f"  {post['date']} {post['slug']} {post['title']}")
    return posts


def main() -> int:
    build(ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
