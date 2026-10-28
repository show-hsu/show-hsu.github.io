#!/usr/bin/env python3
"""產生 Show 的金融保險理財日報。只使用 Python 標準庫。"""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
WEEKDAYS = "一二三四五六日"
CATEGORY_RANK = {"retire": 4, "insurance": 3, "macro": 2, "invest": 1}
USER_AGENT = "ShowDailyNews/1.0 (+https://show-hsu.github.io)"
PLACEHOLDER = """<!--
【今日小評】編輯區
這份檔案對應 {date} 的日報。包在註解裡的文字不會出現在網站上。

寫法：
1. 刪掉這整段 HTML 註解。
2. 用一般文字寫下今天想跟客戶說的話，段落之間空一行。建議 100 到 300 字。
3. 不要貼上媒體全文，不要寫客戶姓名、電話或其他個資。
4. 推上 main。網站會重畫該日頁面，不會重抓新聞。

範例（放在註解裡就不會公開）：
利率還在高檔時，先看這筆保費自己扛不扛得住，再談其他數字。
-->
"""


@dataclass
class Item:
    title: str
    url: str
    source: str
    published: datetime
    snippet: str
    feed_id: str
    category: str
    max_age_hours: int
    extend_age_hours: int
    image: str = ""

    def to_json(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published.isoformat(timespec="seconds"),
            "snippet": self.snippet,
            "feed_id": self.feed_id,
            "image": self.image,
            "image_source": "feed" if self.image else "",
        }


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def cjk_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw or "")
    raw = re.sub(r"(?is)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?is)</p>", "\n", raw)
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    raw = html.unescape(html.unescape(raw))
    raw = raw.replace("\xa0", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n{2,}", "\n", raw)
    return raw.strip()


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，。、；,; ") + "…"


def parse_datetime(value: str, zone: ZoneInfo) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


SECTION_TAILS = {
    "基金",
    "股市",
    "金融",
    "理財",
    "投資理財",
    "國際",
    "生活",
    "社會",
    "證券",
    "產業",
    "要聞",
}
OUTLET_HINTS = (
    "新聞",
    "時報",
    "日報",
    "財經",
    "週刊",
    "雜誌",
    "情報",
    "焦點",
    "財經雲",
    "taiwan",
    "hong",
    "香港",
    "yahoo",
    "ctwant",
    "udn",
    "business insider",
    "investing",
    "關鍵評論",
    "mirror",
    "網誌",
)
TOPIC_PHRASES = (
    "楊金龍",
    "柳樹理論",
    "勞保年金",
    "勞退",
    "宣告利率",
    "台積電",
    "主動式",
    "跨國債券",
    "實支實付",
    "詐保",
    "命案",
    "年金",
    "公務員",
)
TITLE_SEPS = (" - ", " | ", "｜", " – ", " — ", "-", "|")


def split_outlet(title: str) -> tuple[str, str]:
    for sep in TITLE_SEPS:
        if sep in title:
            head, tail = title.rsplit(sep, 1)
            tail = tail.strip()
            if head.strip() and 2 <= len(tail) <= 18:
                return head.strip(), tail
    return title.strip(), ""


def looks_like_outlet(tail: str, source: str) -> bool:
    tail = tail.strip()
    if not tail or any(mark in tail for mark in "。！？?!"):
        return False
    source = source.strip()
    if source and (tail == source or (len(tail) >= 4 and tail in source)):
        return True
    if len(tail) > 28:
        return False
    if tail in SECTION_TAILS:
        return True
    folded = tail.lower()
    if any(hint in folded for hint in OUTLET_HINTS):
        return True
    return "etf" in folded and len(tail) <= 12


def clean_source(source: str) -> str:
    source = html_to_text(source)
    source = re.split(r"\s*[-|｜–—]\s*", source)[0].strip()
    if "鏡週刊" in source or "Mirror Media" in source:
        return "鏡週刊"
    if "關鍵評論" in source or source.startswith("TNL"):
        return "關鍵評論網"
    if "Business Insider" in source:
        return "Business Insider"
    source = re.sub(r"\s+", " ", source)
    if len(source) > 18:
        source = source[:18].rstrip()
    return source or "綜合"


def clean_title(title: str, source: str, limit: int) -> str:
    title = html_to_text(title)
    title = re.sub(r"^[【\[［][^】\]］]{1,12}[】\]］]\s*", "", title).strip()
    title = re.sub(r"^《[^》]{1,6}》\s*", "", title).strip()
    if "/" in title[:28] or "／" in title[:28]:
        parts = re.split(r"[/／]", title, maxsplit=3)
        if len(parts) >= 2 and len(parts[-1].strip()) >= 12 and all(len(part.strip()) <= 18 for part in parts[:-1]):
            title = parts[-1].strip()
    for _ in range(4):
        stripped = False
        for sep in TITLE_SEPS:
            if sep not in title:
                continue
            head, tail = title.rsplit(sep, 1)
            if looks_like_outlet(tail, source) and len(head.strip()) >= 8:
                title = head.strip()
                stripped = True
                break
        if not stripped:
            break
    title = re.sub(r"\s*作者[:：\s]\S.{0,24}$", "", title).strip()
    title = re.sub(r"\s+", " ", title).strip(" -|｜")
    return truncate(title, limit)


def reject_title(title: str) -> bool:
    if title.startswith("更正") or "更正-" in title or "更正—" in title:
        return True
    if title.count("「") != title.count("」") or title.count("（") != title.count("）"):
        return True
    if any(word in title for word in ("開募", "立即申購", "限時優惠", "截肢", "凍爛")):
        return True
    if any(word in title for word in ("國民黨", "民進黨", "民眾黨", "柯文哲", "賴清德", "藍營", "綠營", "中共", "公僕")):
        return True
    foreign = ("紐西蘭", "新西蘭", "歐元區", "歐洲央行", "歐元", "紐元", "英鎊", "英國央行", "澳洲聯準", "土耳其", "里拉", "南非", "美聯儲", "泰國", "泰銖", "甘肅", "公帑", "港元")
    local = ("台灣", "新台幣", "台股", "金管會", "勞保", "勞退")
    if any(word in title for word in foreign) and not any(word in title for word in local):
        return True
    if re.search(r"[A-Za-z]{3,}", title) and any(word in title for word in ("財報", "股價", "執行長", "費率")) and not any(word in title for word in local):
        return True
    letters = re.findall(r"[A-Za-z]{8,}", title)
    allowed = {"business", "insider"}
    if any(token.lower() not in allowed for token in letters):
        return True
    return False


def topic_keys(title: str) -> set[str]:
    keys = set(re.findall(r"\d{4,6}", title))
    keys.update(phrase for phrase in TOPIC_PHRASES if phrase in title)
    return keys


def clean_snippet(raw: str, title: str, limit: int) -> str:
    text = html_to_text(raw)
    text = re.sub(r"^（中央社[^）]{0,40}）", "", text).strip()
    text = re.sub(r"^〔[^〕]{0,24}〕", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 24:
        return ""
    compact_text = re.sub(r"\s+", "", text)
    compact_title = re.sub(r"\s+", "", title)
    if not compact_text or compact_text == compact_title or compact_text in compact_title:
        return ""
    if compact_title in compact_text and len(compact_text) < len(compact_title) + 12:
        return ""
    return truncate(text, limit)


def canonical_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    query = [
        (key, val)
        for key, val in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "igshid", "gclid"}
    ]
    path = parts.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urllib.parse.urlencode(query), "")
    )


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).lower()
    text = re.sub(r"^[【\[［][^】\]］]{1,12}[】\]］]", "", text)
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text)


def bigrams(text: str) -> set[str]:
    return {text[i : i + 2] for i in range(len(text) - 1)}


def similar(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= 10 and shorter in longer and len(shorter) / len(longer) >= 0.6:
        return True
    if len(shorter) < 8:
        return False
    left_grams, right_grams = bigrams(left), bigrams(right)
    if not left_grams or not right_grams:
        return False
    return len(left_grams & right_grams) / len(left_grams | right_grams) >= 0.8


def child_text(node: ET.Element, name: str) -> str:
    for child in list(node):
        if local_name(child.tag) == name:
            text = "".join(child.itertext()).strip()
            if text:
                return text
            return (child.attrib.get("href") or "").strip()
    return ""


def keyword_in(text: str, word: str) -> bool:
    if not word:
        return False
    if word == "利率":
        return re.search(r"(?<![毛殖淨報酬配存貸])利率", text) is not None
    return word in text


def on_topic(title: str, snippet: str, category: str, settings: dict) -> bool:
    rules = settings["classifier"]
    words = list(rules.get(category, []))
    if category == "invest":
        words.extend(rules.get("invest_first", []))
    return any(keyword_in(title, word) for word in words)


def classify(title: str, snippet: str, feed_category: str, settings: dict) -> str:
    if feed_category:
        return feed_category
    text = f"{title} {snippet}"
    rules = settings["classifier"]
    for category in ("insurance", "retire", "invest_first", "macro", "invest"):
        if any(keyword_in(text, word) for word in rules.get(category, [])):
            return "invest" if category == "invest_first" else category
    return ""


COVERS = {
    "insurance": "/assets/covers/insurance.svg",
    "invest": "/assets/covers/invest.svg",
    "macro": "/assets/covers/macro.svg",
    "retire": "/assets/covers/retire.svg",
}
GENERIC_IMAGE = re.compile(
    r"(favicon|sprite|1x1|pixel|spacer|blank\.|logo|pic_fb|default[-_]og|og[-_]default|noimage|no-image|/default/)",
    re.I,
)
OG_PATTERNS = (
    re.compile(
        r"""<meta[^>]+property=["']og:image(?::secure_url)?["'][^>]+content=["']([^"']+)["']""",
        re.I,
    ),
    re.compile(
        r"""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:image(?::secure_url)?["']""",
        re.I,
    ),
    re.compile(
        r"""<meta[^>]+name=["']twitter:image(?::src)?["'][^>]+content=["']([^"']+)["']""",
        re.I,
    ),
    re.compile(
        r"""<meta[^>]+content=["']([^"']+)["'][^>]+name=["']twitter:image(?::src)?["']""",
        re.I,
    ),
)


def cover_for(category_id: str) -> str:
    return COVERS.get(category_id, COVERS["invest"])


def plausible_image(url: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    if len(url) > 800 or GENERIC_IMAGE.search(url):
        return False
    return True


def normalize_image_url(url: str, base: str = "") -> str:
    url = html.unescape((url or "").strip())
    if url.startswith("//"):
        url = "https:" + url
    elif base and not url.startswith(("http://", "https://")):
        url = urllib.parse.urljoin(base, url)
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url if plausible_image(url) else ""


def feed_image(node: ET.Element) -> str:
    found: list[tuple[int, str]] = []
    elements = list(node)
    for child in list(node):
        elements.extend(list(child))
    for child in elements:
        name = local_name(child.tag)
        if name in {"thumbnail", "content"}:
            url = (child.attrib.get("url") or "").strip()
            medium = (child.attrib.get("medium") or "").lower()
            mime = (child.attrib.get("type") or "").lower()
            width = child.attrib.get("width") or ""
            if medium == "video" or mime.startswith("video"):
                continue
            if width.isdigit() and int(width) < 80:
                continue
            if url:
                found.append((int(width) if width.isdigit() else 0, url))
        elif name == "enclosure":
            url = (child.attrib.get("url") or "").strip()
            mime = (child.attrib.get("type") or "").lower()
            if url and (mime.startswith("image") or re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.I)):
                found.append((0, url))
    found.sort(key=lambda pair: pair[0], reverse=True)
    for _, url in found:
        cleaned = normalize_image_url(url)
        if cleaned:
            return cleaned
    return ""


def extract_og_image(page: str, base_url: str) -> str:
    for pattern in OG_PATTERNS:
        match = pattern.search(page)
        if match:
            image = normalize_image_url(match.group(1), base_url)
            if image:
                return image
    return ""


def fetch_og_image(url: str, timeout: float = 4.0) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-TW,zh;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            chunks: list[bytes] = []
            total = 0
            while total < 120_000:
                part = response.read(8192)
                if not part:
                    break
                chunks.append(part)
                total += len(part)
                if b"og:image" in part or b"twitter:image" in b"".join(chunks):
                    extra = response.read(4000)
                    if extra:
                        chunks.append(extra)
                    break
            page = b"".join(chunks).decode("utf-8", "replace")
    except Exception:
        return ""
    return extract_og_image(page, final_url)


def enrich_images(edition: dict, fetch_og=fetch_og_image) -> None:
    pending = []
    for category in edition["categories"]:
        for item in category["items"]:
            if item.get("image"):
                item["image_source"] = "feed"
            else:
                pending.append(item)
    found: dict[str, str] = {}
    if pending:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(fetch_og, item["url"]): item["url"] for item in pending}
            for future in as_completed(futures):
                target = futures[future]
                try:
                    found[target] = future.result() or ""
                except Exception:
                    found[target] = ""
    counts = {"feed": 0, "og": 0, "default": 0}
    for category in edition["categories"]:
        fallback = cover_for(category["id"])
        for item in category["items"]:
            if item.get("image"):
                counts["feed"] += 1
                continue
            image = found.get(item["url"], "")
            if image:
                item["image"] = image
                item["image_source"] = "og"
                counts["og"] += 1
            else:
                item["image"] = fallback
                item["image_source"] = "default"
                counts["default"] += 1
    print(f"圖片：來源 {counts['feed']}、原文 og:image {counts['og']}、分類插圖 {counts['default']}")


def parse_feed(xml_bytes: bytes, feed: dict, settings: dict, now: datetime) -> tuple[list[Item], int]:
    if not xml_bytes or xml_bytes.lstrip()[:1] not in (b"<", b"\xef"):
        raise ValueError("回應不是 XML")
    root = ET.fromstring(xml_bytes)
    items: list[Item] = []
    fetched = 0
    limit = int(settings["title_chars"])
    snippet_limit = int(settings["snippet_chars"])
    zone = now.tzinfo
    for node in root.iter():
        if local_name(node.tag) != "item":
            continue
        raw_title = child_text(node, "title")
        url = child_text(node, "link") or child_text(node, "guid")
        if not raw_title or not url.startswith(("http://", "https://")):
            continue
        fetched += 1
        raw_source = child_text(node, "source") or feed.get("source") or ""
        if raw_source.startswith("http"):
            raw_source = feed.get("source") or ""
        blocked = f"{raw_title} {raw_source}"
        if any(word and word in blocked for word in settings.get("block_words", [])):
            continue
        if re.search(r"(?i)basketball|instagram|tiktok|dcard", blocked):
            continue
        title = clean_title(raw_title, raw_source, limit)
        source = clean_source(raw_source)
        if source == "綜合" or not raw_source:
            _, tail = split_outlet(html_to_text(raw_title))
            source = clean_source(tail or feed.get("source") or feed.get("label") or "綜合")
        if cjk_count(title) < 4 or reject_title(title):
            continue
        published = parse_datetime(child_text(node, "pubDate") or child_text(node, "date"), zone)
        if published is None:
            continue
        age_hours = (now - published).total_seconds() / 3600
        if age_hours < -12 or age_hours > float(feed["extend_age_hours"]):
            continue
        snippet = clean_snippet(child_text(node, "description"), title, snippet_limit)
        category = classify(title, snippet, feed.get("category") or "", settings)
        if not category or not on_topic(title, snippet, category, settings):
            continue
        items.append(
            Item(
                title=title,
                url=url.strip(),
                source=source.strip() or "綜合",
                published=published,
                snippet=snippet,
                feed_id=feed["id"],
                category=category,
                max_age_hours=int(feed["max_age_hours"]),
                extend_age_hours=int(feed["extend_age_hours"]),
                image=feed_image(node),
            )
        )
    return items, fetched


def content_rank(item: Item) -> tuple:
    direct = 0 if "news.google.com" in item.url else 1
    return (direct, 1 if item.snippet else 0, len(item.snippet), item.published.timestamp())


def merge_items(left: Item, right: Item) -> Item:
    if CATEGORY_RANK.get(left.category, 0) > CATEGORY_RANK.get(right.category, 0):
        primary, secondary = left, right
    elif CATEGORY_RANK.get(right.category, 0) > CATEGORY_RANK.get(left.category, 0):
        primary, secondary = right, left
    elif content_rank(left) >= content_rank(right):
        primary, secondary = left, right
    else:
        primary, secondary = right, left
    category = primary.category
    if CATEGORY_RANK.get(secondary.category, 0) > CATEGORY_RANK.get(primary.category, 0):
        category = secondary.category
    use_secondary_url = "news.google.com" in primary.url and "news.google.com" not in secondary.url
    if use_secondary_url:
        url, source, title = secondary.url, secondary.source or primary.source, secondary.title or primary.title
        published = secondary.published
    else:
        url, source, title = primary.url, primary.source or secondary.source, primary.title
        published = primary.published
    snippet = primary.snippet
    if len(secondary.snippet) > len(snippet):
        snippet = secondary.snippet
    return replace(
        primary,
        title=title,
        url=url,
        source=source,
        published=published,
        snippet=snippet,
        category=category,
        max_age_hours=max(left.max_age_hours, right.max_age_hours),
        extend_age_hours=max(left.extend_age_hours, right.extend_age_hours),
    )


def dedupe(items: list[Item]) -> list[Item]:
    kept: list[Item] = []
    keys: list[str] = []
    urls: list[str] = []
    for item in sorted(items, key=content_rank, reverse=True):
        title_key = normalize_title(item.title)
        url_key = canonical_url(item.url)
        match = None
        for index, prev in enumerate(kept):
            if url_key == urls[index] or similar(title_key, keys[index]):
                match = index
                break
        if match is None:
            kept.append(item)
            keys.append(title_key)
            urls.append(url_key)
        else:
            merged = merge_items(kept[match], item)
            kept[match] = merged
            keys[match] = normalize_title(merged.title)
            urls[match] = canonical_url(merged.url)
    return kept


def age_hours(item: Item, now: datetime) -> float:
    return (now - item.published).total_seconds() / 3600


def select_category(items: list[Item], category: str, settings: dict, now: datetime) -> list[Item]:
    pool = [item for item in items if item.category == category]
    primary = dedupe([item for item in pool if age_hours(item, now) <= item.max_age_hours])
    if len(primary) < int(settings["min_before_extend"]):
        older = [
            item
            for item in pool
            if item.max_age_hours < age_hours(item, now) <= item.extend_age_hours
        ]
        primary = dedupe(primary + older)
    boosts = settings.get("boost", {}).get(category, [])
    per_source = int(settings["per_source"])
    per_topic = int(settings.get("per_topic", 2))
    limit = int(settings["per_category"])
    offshore_words = ("內險", "港股", "恆生", "A股", "人行")
    local_words = ("台灣", "金管會", "新台幣", "台股", "勞保", "勞退")

    def sort_key(item: Item) -> tuple:
        age = max(age_hours(item, now), -1)
        text = f"{item.title} {item.snippet}"
        boost = sum(1 for word in boosts if word and word in text)
        direct = 0 if "news.google.com" in item.url else 1
        offshore = 1 if any(word in text for word in offshore_words) and not any(word in text for word in local_words) else 0
        scandal = 1 if any(word in item.title for word in ("詐保", "命案", "假摔")) else 0
        return (int(age // 12) + offshore + scandal, -boost, -direct, 0 if item.snippet else 1, age, item.title)

    def crowded(item: Item, chosen: list[Item], topic_counts: dict[str, int]) -> bool:
        if any(topic_counts.get(key, 0) >= per_topic for key in topic_keys(item.title)):
            return True
        current = normalize_title(item.title)
        for prev in chosen:
            previous = normalize_title(prev.title)
            if similar(current, previous):
                return True
            shorter, longer = sorted((current, previous), key=len)
            if len(shorter) >= 10 and shorter in longer:
                return True
            if len(current) >= 8 and len(previous) >= 8:
                left, right = bigrams(current), bigrams(previous)
                if left and right and len(left & right) / len(left | right) >= 0.48:
                    return True
        return False

    ranked = sorted(primary, key=sort_key)
    chosen: list[Item] = []
    counts: dict[str, int] = {}
    topic_counts: dict[str, int] = {}
    deferred: list[Item] = []

    def take(item: Item) -> None:
        chosen.append(item)
        counts[item.source] = counts.get(item.source, 0) + 1
        for key in topic_keys(item.title):
            topic_counts[key] = topic_counts.get(key, 0) + 1

    for item in ranked:
        if counts.get(item.source, 0) >= per_source or crowded(item, chosen, topic_counts):
            deferred.append(item)
            continue
        take(item)
        if len(chosen) >= limit:
            break
    if len(chosen) < limit:
        for item in deferred:
            if counts.get(item.source, 0) >= per_source or crowded(item, chosen, topic_counts):
                continue
            take(item)
            if len(chosen) >= limit:
                break
    chosen.sort(key=lambda item: (item.published, item.title), reverse=True)
    return chosen


def build_edition(items: list[Item], statuses: list[dict], settings: dict, now: datetime) -> dict:
    deduped = dedupe(items)
    categories = []
    for category in settings["categories"]:
        chosen = select_category(deduped, category["id"], settings, now)
        categories.append(
            {
                "id": category["id"],
                "name": category["name"],
                "blurb": category["blurb"],
                "stale_hours": category["stale_hours"],
                "items": [item.to_json() for item in chosen],
            }
        )
    return {
        "version": 1,
        "date": now.date().isoformat(),
        "generated_at": now.isoformat(timespec="seconds"),
        "feed_status": statuses,
        "categories": categories,
    }


def edition_count(edition: dict) -> int:
    return sum(len(category["items"]) for category in edition["categories"])


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "Accept-Language": "zh-TW,zh;q=0.9",
        },
    )
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read(2_000_000)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt == 0:
                time.sleep(1.2)
    assert last_error is not None
    raise last_error


def gather(feeds: list[dict], settings: dict, now: datetime, fetch=fetch_bytes) -> tuple[list[Item], list[dict]]:
    enabled = [feed for feed in feeds if feed.get("enabled", True)]
    results: dict[str, tuple[list[Item], dict]] = {}

    def one(feed: dict) -> tuple[str, list[Item], dict]:
        try:
            payload = fetch(feed["url"])
            items, fetched = parse_feed(payload, feed, settings, now)
            status = {
                "id": feed["id"],
                "label": feed["label"],
                "ok": True,
                "fetched": fetched,
                "kept": len(items),
                "error": "",
            }
            return feed["id"], items, status
        except Exception as error:  # noqa: BLE001 — 單一來源失敗不應中斷整份日報
            message = f"{type(error).__name__}: {error}"
            status = {
                "id": feed["id"],
                "label": feed["label"],
                "ok": False,
                "fetched": 0,
                "kept": 0,
                "error": message[:300],
            }
            return feed["id"], [], status

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(one, feed) for feed in enabled]
        for future in as_completed(futures):
            feed_id, items, status = future.result()
            results[feed_id] = (items, status)

    items: list[Item] = []
    statuses: list[dict] = []
    for feed in enabled:
        parsed, status = results[feed["id"]]
        items.extend(parsed)
        statuses.append(status)
        if status["ok"]:
            print(f"[ok] {status['label']} 取得 {status['fetched']} 則，留下 {status['kept']} 則")
        else:
            print(f"[略過] {status['label']} {status['error']}")
    return items, statuses


def prose_to_html(text: str) -> str:
    stripped = re.sub(r"<!--.*?-->", "", text or "", flags=re.S).strip()
    if not stripped:
        return ""
    blocks = re.split(r"\n\s*\n", stripped)
    parts = []
    for block in blocks:
        lines = [esc(line.strip()) for line in block.splitlines() if line.strip()]
        if lines:
            parts.append("<p>" + "<br>\n".join(lines) + "</p>")
    return "\n".join(parts)


def read_prose(path: Path) -> str:
    if not path.exists():
        return ""
    return prose_to_html(path.read_text(encoding="utf-8"))


def format_date(day: datetime) -> str:
    return f"{day.year}年{day.month}月{day.day}日"


def format_clock(moment: datetime) -> str:
    local = moment
    return f"{local.month}月{local.day}日 {local.hour:02d}:{local.minute:02d}"


def weekday_label(day: datetime) -> str:
    return "星期" + WEEKDAYS[day.weekday()]


def description_for(edition: dict, limit: int = 110) -> str:
    titles = []
    for category in edition["categories"]:
        if category["items"]:
            titles.append(category["items"][0]["title"])
    if not titles:
        return "每天整理保險、理財、利率與退休相關新聞標題。"
    day = datetime.fromisoformat(edition["date"])
    text = f"{format_date(day)}重點：" + "；".join(titles)
    return truncate(text, limit)


def render_thumb(item: dict, category_id: str) -> str:
    fallback = cover_for(category_id)
    src = item.get("image") or fallback
    if not (src.startswith("https://") or src.startswith("/assets/")):
        src = fallback
    attrs = 'alt="" loading="lazy" decoding="async" width="640" height="360"'
    if src == fallback:
        return f'<span class="thumb"><img src="{esc(src)}" {attrs}></span>'
    return (
        f'<span class="thumb"><img src="{esc(src)}" {attrs} '
        f'data-fallback="{esc(fallback)}" '
        'onerror="this.onerror=null;this.src=this.dataset.fallback"></span>'
    )


def render_stories(category: dict, zone: ZoneInfo, generated_at: datetime) -> str:
    stale_hours = int(category.get("stale_hours") or 72)
    moments = [datetime.fromisoformat(item["published_at"]) for item in category["items"]]
    newest = max(moments) if moments else generated_at
    stale = ""
    if moments and (generated_at - newest) > timedelta(hours=stale_hours):
        stale = '<p class="stale">這個主題這幾天更新不多，以下含較早的報導。</p>'
    cards = []
    for item in category["items"]:
        published = datetime.fromisoformat(item["published_at"]).astimezone(zone)
        snippet = f'<p class="snippet">{esc(item["snippet"])}</p>' if item.get("snippet") else ""
        cards.append(
            "<li>"
            f'<a class="story" href="{esc(item["url"])}" target="_blank" rel="noopener noreferrer">'
            f'{render_thumb(item, category["id"])}'
            '<span class="story-body">'
            f"<h3>{esc(item['title'])}</h3>"
            '<span class="vh">（另開原文）</span>'
            f"{snippet}"
            '<p class="meta">'
            f'<span class="source">{esc(item["source"])}</span>'
            f'<time datetime="{esc(published.isoformat(timespec="seconds"))}">{esc(format_clock(published))}</time>'
            "</p></span></a></li>"
        )
    return stale + '<ol class="stories">' + "".join(cards) + "</ol>"


def render_edition_main(edition: dict, settings: dict, about_html: str, commentary_html: str, *, is_home: bool) -> str:
    zone = ZoneInfo(settings["timezone"])
    day = datetime.fromisoformat(edition["date"]).replace(tzinfo=zone)
    generated_at = datetime.fromisoformat(edition["generated_at"]).astimezone(zone)
    count = edition_count(edition)
    kicker = "今日日報" if is_home else "日報存檔"
    title = settings["site_name"] if is_home else format_date(day)
    heading = (
        f'<p class="kicker">{kicker}</p>'
        f"<h1>{esc(title)}</h1>"
        f'<p class="edition-date"><time datetime="{esc(edition["date"])}">{esc(format_date(day))}</time> · {weekday_label(day)}</p>'
        f'<p class="edition-meta">共 {count} 則 · 整理時間 {generated_at.hour:02d}:{generated_at.minute:02d}（台北時間）</p>'
    )
    parts = ['<article class="edition">']
    if is_home:
        parts.append(
            '<figure class="hero">'
            '<img src="/assets/hero.svg" alt="" width="1200" height="640" fetchpriority="high">'
            f"<figcaption>{heading}</figcaption>"
            "</figure>"
        )
        parts.append(f'<p class="share-row"><a href="/archive/{esc(edition["date"])}/">這一天的固定網址</a></p>')
    else:
        parts.append(f'<header class="edition-head">{heading}</header>')
    parts.append('<p class="lead">點卡片可看原文。這裡只留來源、時間、短摘要，以及一張縮圖。</p>')
    visible = [category for category in edition["categories"] if category["items"]]
    if visible:
        chips = []
        for category in visible:
            chips.append(
                f'<a href="#{esc(category["id"])}">{esc(category["name"])}'
                f'<span>{len(category["items"])}</span></a>'
            )
        parts.append('<nav class="jump" aria-label="分類">' + "".join(chips) + "</nav>")
    if commentary_html:
        note_label = "今日小評" if is_home else "當日小評"
        parts.append(
            '<section class="commentary" aria-labelledby="commentary-title">'
            f'<p class="kicker">{note_label}</p>'
            '<h2 id="commentary-title">Show 的短評</h2>'
            f'<p class="byline">{esc(settings["owner_name"])}</p>'
            f'<div class="prose">{commentary_html}</div>'
            "</section>"
        )
    if not visible:
        parts.append('<p class="empty">今天沒有符合條件的新報導。上一版頁面會保留到下一次成功更新。</p>')
    for index, category in enumerate(visible, start=1):
        parts.append(
            f'<section class="category" id="{esc(category["id"])}">'
            '<div class="cat-head">'
            f'<span class="cat-no">{index:02d}</span>'
            "<div>"
            f'<h2>{esc(category["name"])}<span class="cat-count">{len(category["items"])} 則</span></h2>'
            f'<p>{esc(category["blurb"])}</p>'
            "</div></div>"
            + render_stories(category, zone, generated_at)
            + "</section>"
        )
    sources = []
    for category in visible:
        for item in category["items"]:
            if item["source"] not in sources:
                sources.append(item["source"])
    if sources:
        parts.append(f'<p class="sources">本日來源：{esc("、".join(sources))}</p>')
    if is_home and about_html:
        parts.append(
            '<section class="about" id="about">'
            "<h2>關於 Show</h2>"
            f'<div class="prose">{about_html}</div>'
            "</section>"
        )
    parts.append("</article>")
    return "\n".join(parts)


def render_archive_main(editions: list[dict], settings: dict) -> str:
    zone = ZoneInfo(settings["timezone"])
    rows = []
    for edition in sorted(editions, key=lambda item: item["date"], reverse=True):
        day = datetime.fromisoformat(edition["date"]).replace(tzinfo=zone)
        rows.append(
            "<li><a "
            f'href="/archive/{esc(edition["date"])}/">'
            f'<time datetime="{esc(edition["date"])}">{esc(format_date(day))}</time>'
            f'<span class="archive-count">{weekday_label(day)} · {edition_count(edition)} 則</span>'
            "</a></li>"
        )
    body = "".join(rows) or '<p class="empty">還沒有日報。</p>'
    return (
        '<article class="archive-block">'
        '<p class="kicker">ARCHIVE</p>'
        "<h1>日報彙整</h1>"
        '<p class="lead">每天一份。點進去可以看當天的標題整理，以及那天如果有寫的小評。</p>'
        f'<ol class="archive-list">{body}</ol>'
        "</article>"
    )


def render_about_main(about_html: str) -> str:
    return (
        '<article class="about">'
        '<p class="kicker">ABOUT</p>'
        "<h1>關於 Show</h1>"
        f'<div class="prose">{about_html}</div>'
        '<p class="share-row"><a class="back-link" href="/">回到今日日報</a></p>'
        "</article>"
    )


def apply_template(template: str, mapping: dict[str, str]) -> str:
    page = template
    for key, value in mapping.items():
        page = page.replace(f"@@{key}@@", value)
    leftover = re.findall(r"@@[A-Z_]+@@", page)
    if leftover:
        raise RuntimeError(f"模板還有未替換的標記：{', '.join(leftover)}")
    return page


def json_ld(name: str, url: str, description: str) -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": name,
        "url": url,
        "description": description,
        "inLanguage": "zh-Hant",
        "isAccessibleForFree": True,
    }
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def page(
    template: str,
    settings: dict,
    *,
    title: str,
    description: str,
    canonical: str,
    main: str,
    current: str,
    extra_head: str = "",
) -> str:
    nav = {"TODAY": "", "ARCHIVE": "", "ABOUT": ""}
    if current in nav:
        nav[current] = 'aria-current="page"'
    year = str(datetime.now(ZoneInfo(settings["timezone"])).year)
    return apply_template(
        template,
        {
            "TITLE": esc(title),
            "DESCRIPTION": esc(description),
            "CANONICAL": esc(canonical),
            "OG_TITLE": esc(title),
            "OG_IMAGE": esc(settings["site_url"].rstrip("/") + "/assets/og.png"),
            "EXTRA_HEAD": extra_head,
            "JSONLD": json_ld(title, canonical, description),
            "NAV_TODAY": nav["TODAY"],
            "NAV_ARCHIVE": nav["ARCHIVE"],
            "NAV_ABOUT": nav["ABOUT"],
            "MAIN": main,
            "YEAR": year,
        },
    )


def commentary_path(root: Path, day: str) -> Path:
    return root / "data" / "commentary" / f"{day}.md"


def load_editions(root: Path) -> list[dict]:
    folder = root / "data" / "editions"
    editions = []
    for path in sorted(folder.glob("*.json")):
        editions.append(json.loads(path.read_text(encoding="utf-8")))
    return editions


def write_edition(root: Path, edition: dict) -> None:
    folder = root / "data" / "editions"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{edition['date']}.json"
    path.write_text(json.dumps(edition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    note = commentary_path(root, edition["date"])
    if not note.exists():
        note.write_text(PLACEHOLDER.format(date=edition["date"]), encoding="utf-8")


def pager(editions: list[dict], current: str) -> str:
    dates = [edition["date"] for edition in sorted(editions, key=lambda item: item["date"])]
    if current not in dates:
        return ""
    index = dates.index(current)
    links = []
    if index > 0:
        links.append(f'<a href="/archive/{dates[index - 1]}/">前一天</a>')
    else:
        links.append("<span></span>")
    if index < len(dates) - 1:
        links.append(f'<a href="/archive/{dates[index + 1]}/">後一天</a>')
    else:
        links.append("<span></span>")
    return '<p class="pager">' + "".join(links) + "</p>"


def write_site(root: Path, settings: dict) -> None:
    editions = load_editions(root)
    if not editions:
        raise SystemExit("沒有任何日報資料，無法產生頁面")
    template = (root / "templates" / "layout.html").read_text(encoding="utf-8")
    about_html = read_prose(root / "data" / "about.md")
    latest = max(editions, key=lambda item: item["date"])
    site = settings["site_url"].rstrip("/")
    home_description = description_for(latest)
    home = page(
        template,
        settings,
        title=f"{settings['site_name']}｜{format_date(datetime.fromisoformat(latest['date']))}",
        description=home_description,
        canonical=site + "/",
        main=render_edition_main(
            latest,
            settings,
            about_html,
            read_prose(commentary_path(root, latest["date"])),
            is_home=True,
        ),
        current="TODAY",
    )
    (root / "index.html").write_text(home, encoding="utf-8")

    archive_dir = root / "archive"
    archive_dir.mkdir(exist_ok=True)
    keep = {edition["date"] for edition in editions}
    for child in archive_dir.iterdir():
        if child.is_dir() and child.name not in keep and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name):
            for file in child.glob("*"):
                file.unlink()
            child.rmdir()

    dates = [edition["date"] for edition in sorted(editions, key=lambda item: item["date"])]
    for edition in editions:
        day_dir = archive_dir / edition["date"]
        day_dir.mkdir(exist_ok=True)
        day = datetime.fromisoformat(edition["date"])
        description = description_for(edition)
        canonical = f"{site}/archive/{edition['date']}/"
        extra = ""
        index = dates.index(edition["date"])
        if index > 0:
            extra += f'<link rel="prev" href="{site}/archive/{dates[index - 1]}/">'
        if index < len(dates) - 1:
            extra += f'<link rel="next" href="{site}/archive/{dates[index + 1]}/">'
        html_page = page(
            template,
            settings,
            title=f"{format_date(day)}｜{settings['site_name']}",
            description=description,
            canonical=canonical,
            main=render_edition_main(
                edition,
                settings,
                about_html,
                read_prose(commentary_path(root, edition["date"])),
                is_home=False,
            )
            + pager(editions, edition["date"]),
            current="",
            extra_head=extra,
        )
        (day_dir / "index.html").write_text(html_page, encoding="utf-8")

    archive_html = page(
        template,
        settings,
        title=f"日報彙整｜{settings['site_name']}",
        description="過去每一天的保險、理財、利率與退休新聞整理。",
        canonical=site + "/archive/",
        main=render_archive_main(editions, settings),
        current="ARCHIVE",
    )
    (archive_dir / "index.html").write_text(archive_html, encoding="utf-8")

    about_dir = root / "about"
    about_dir.mkdir(exist_ok=True)
    about_page = page(
        template,
        settings,
        title=f"關於 Show｜{settings['site_name']}",
        description="許欣霈（Show）的金融保險理財日報。",
        canonical=site + "/about/",
        main=render_about_main(about_html),
        current="ABOUT",
    )
    (about_dir / "index.html").write_text(about_page, encoding="utf-8")

    urls = [site + "/", site + "/archive/", site + "/about/"]
    urls.extend(f"{site}/archive/{edition['date']}/" for edition in editions)
    body = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url in urls:
        body.append(f"  <url><loc>{esc(url)}</loc></url>")
    body.append("</urlset>")
    (root / "sitemap.xml").write_text("\n".join(body) + "\n", encoding="utf-8")


def build_today(root: Path, settings: dict, feeds: list[dict]) -> dict:
    now = datetime.now(ZoneInfo(settings["timezone"])).replace(microsecond=0)
    items, statuses = gather(feeds, settings, now)
    edition = build_edition(items, statuses, settings, now)
    total = edition_count(edition)
    if total >= int(settings["min_total_items"]):
        enrich_images(edition)
    print(f"分類後共 {total} 則")
    for category in edition["categories"]:
        print(f"  {category['name']} {len(category['items'])} 則")
        for item in category["items"]:
            print(f"    - {item['source']}｜{item['title']}")
    if total < int(settings["min_total_items"]):
        failed = [status["label"] for status in statuses if not status["ok"]]
        raise SystemExit(
            f"有效新聞只有 {total} 則，低於 {settings['min_total_items']}，不覆蓋現有頁面。"
            + (f" 失敗來源：{'、'.join(failed)}" if failed else "")
        )
    write_edition(root, edition)
    return edition


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="產生金融保險理財日報")
    parser.add_argument("--rebuild-only", action="store_true", help="只依現有 JSON 與小評重畫頁面")
    args = parser.parse_args(argv)
    settings = load_json(ROOT / "config" / "settings.json")
    if args.rebuild_only:
        if not load_editions(ROOT):
            raise SystemExit("尚未有日報資料，無法只重畫頁面")
        print("只重畫頁面，不重抓 RSS")
    else:
        feeds = load_json(ROOT / "config" / "feeds.json")["feeds"]
        build_today(ROOT, settings, feeds)
    write_site(ROOT, settings)
    latest = max(load_editions(ROOT), key=lambda item: item["date"])
    print(f"完成：{latest['date']}，首頁與彙整已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
