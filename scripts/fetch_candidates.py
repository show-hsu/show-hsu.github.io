#!/usr/bin/env python3
"""選題用的 RSS 幫手。只把候選標題印成 JSON，不寫網頁、不提交。"""

from __future__ import annotations

import email.utils
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "ShowDailyNews/1.0 (+https://show-hsu.github.io)"
PER_FEED = 8


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(node: ET.Element, name: str) -> str:
    for child in list(node):
        if local_name(child.tag) == name:
            text = "".join(child.itertext()).strip()
            if text:
                return text
            return (child.attrib.get("href") or "").strip()
    return ""


def parse_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    return parsed.astimezone(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")


def parse_feed(xml_bytes: bytes, feed: dict) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for node in root.iter():
        if local_name(node.tag) != "item":
            continue
        title = child_text(node, "title").strip()
        url = (child_text(node, "link") or child_text(node, "guid")).strip()
        if not title or not url.startswith(("http://", "https://")):
            continue
        source = child_text(node, "source") or feed.get("source") or feed.get("label") or ""
        items.append(
            {
                "title": title,
                "url": url,
                "source": source.strip(),
                "published_at": parse_date(child_text(node, "pubDate") or child_text(node, "date")),
                "feed_id": feed["id"],
                "feed_label": feed.get("label") or feed["id"],
            }
        )
        if len(items) >= PER_FEED:
            break
    return items


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read(2_000_000)


def collect(feeds: list[dict], fetch=fetch_bytes) -> dict:
    candidates = []
    errors = []
    for feed in feeds:
        if not feed.get("enabled", True):
            continue
        try:
            payload = fetch(feed["url"])
            found = parse_feed(payload, feed)
            candidates.extend(found)
            print(f"[ok] {feed.get('label', feed['id'])} {len(found)} 則", file=sys.stderr)
        except (ET.ParseError, urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            errors.append({"id": feed["id"], "label": feed.get("label", feed["id"]), "error": f"{type(error).__name__}: {error}"[:300]})
            print(f"[略過] {feed.get('label', feed['id'])} {error}", file=sys.stderr)
    return {
        "generated_at": datetime.now(ZoneInfo("Asia/Taipei")).replace(microsecond=0).isoformat(),
        "candidates": candidates,
        "errors": errors,
    }


def main() -> int:
    feeds = json.loads((ROOT / "config" / "feeds.json").read_text(encoding="utf-8"))["feeds"]
    report = collect(feeds)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if report["candidates"] else 1


if __name__ == "__main__":
    sys.exit(main())
