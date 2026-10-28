#!/usr/bin/env python3
"""離線測試。不連網，也不寫入正式日報。"""

from __future__ import annotations

import sys
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 10, 28, 15, 40, tzinfo=ZONE)

SETTINGS = {
    "title_chars": 140,
    "snippet_chars": 90,
    "block_words": ["賭博"],
    "classifier": {
        "insurance": ["保險", "壽險", "金管會"],
        "retire": ["退休", "勞退"],
        "invest_first": ["ETF", "理財"],
        "macro": ["利率", "匯率", "央行"],
        "invest": ["台股"],
    },
    "boost": {
        "insurance": ["壽險"],
        "invest": ["台股"],
        "macro": ["利率"],
        "retire": ["退休"],
    },
    "per_source": 2,
    "per_category": 3,
    "min_before_extend": 2,
    "timezone": "Asia/Taipei",
    "site_name": "Show 的金融保險理財日報",
    "site_url": "https://show-hsu.github.io",
    "owner_name": "許欣霈",
    "categories": [
        {"id": "insurance", "name": "保險新聞", "blurb": "保單", "stale_hours": 72},
        {"id": "invest", "name": "理財投資", "blurb": "台股", "stale_hours": 36},
        {"id": "macro", "name": "總經與利率", "blurb": "利率", "stale_hours": 96},
        {"id": "retire", "name": "退休與稅務", "blurb": "退休", "stale_hours": 168},
    ],
}

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <item>
      <title>壽險保費調整方式說明 - 經濟日報</title>
      <link>https://money.udn.com/story/1</link>
      <pubDate>Wed, 28 Oct 2026 07:15:11 GMT</pubDate>
      <source url="https://money.udn.com">經濟日報</source>
      <description><![CDATA[（中央社台北28日電）主管機關說明壽險保費調整方式，投保前要先看自己的現金流是否扛得住。]]></description>
      <content:encoded><![CDATA[這是不該出現的全文這是不該出現的全文這是不該出現的全文]]></content:encoded>
      <media:thumbnail url="https://img.example.com/life.jpg" width="380" height="214"/>
    </item>
    <item>
      <title>Gambling note</title>
      <link>https://example.com/en</link>
      <pubDate>Wed, 28 Oct 2026 07:15:11 GMT</pubDate>
      <description>english only story without enough han characters in the title</description>
    </item>
    <item>
      <title>線上賭博盤算</title>
      <link>https://example.com/bad</link>
      <pubDate>Wed, 28 Oct 2026 06:00:00 GMT</pubDate>
      <description>這則標題含有封鎖詞，不該進入客戶看的日報頁面裡面。</description>
    </item>
    <item>
      <title><![CDATA[<script>alert(1)</script> 台股收盤上漲逾九百點]]></title>
      <link>https://news.cnyes.com/news/id/1</link>
      <pubDate>Wed, 28 Oct 2026 06:00:00 GMT</pubDate>
      <description>加權指數收盤上漲，成交量同時放大，權值股帶動大盤走高，投資人留意隔日波動。</description>
    </item>
  </channel>
</rss>
""".encode()


def item(**kwargs) -> generate.Item:
    base = dict(
        title="壽險保單調整",
        url="https://example.com/a",
        source="中央社",
        published=NOW - timedelta(hours=2),
        snippet="這是一段足夠長度的摘要，用來確認頁面只留短句。",
        feed_id="sample",
        category="insurance",
        max_age_hours=48,
        extend_age_hours=120,
    )
    base.update(kwargs)
    return generate.Item(**base)


class GenerateTests(unittest.TestCase):
    def test_parse_feed_keeps_snippet_and_drops_full_text(self):
        feed = {
            "id": "sample",
            "label": "測試",
            "source": "",
            "category": "",
            "max_age_hours": 48,
            "extend_age_hours": 120,
        }
        items, fetched = generate.parse_feed(SAMPLE_RSS, feed, SETTINGS, NOW)
        self.assertEqual(fetched, 4)
        self.assertEqual(len(items), 2)
        insurance = next(entry for entry in items if entry.category == "insurance")
        self.assertEqual(insurance.title, "壽險保費調整方式說明")
        self.assertEqual(insurance.source, "經濟日報")
        self.assertEqual(insurance.published.hour, 15)
        self.assertIn("現金流", insurance.snippet)
        self.assertNotIn("不該出現的全文", insurance.snippet)
        self.assertNotIn("中央社台北", insurance.snippet)
        self.assertEqual(insurance.image, "https://img.example.com/life.jpg")
        stock = next(entry for entry in items if entry.category == "invest")
        self.assertNotIn("<script>", stock.title)
        self.assertIn("台股收盤", stock.title)

    def test_failed_feed_does_not_drop_others(self):
        feeds = [
            {
                "id": "good",
                "label": "好的來源",
                "url": "https://example.com/good.xml",
                "source": "中央社",
                "category": "insurance",
                "max_age_hours": 48,
                "extend_age_hours": 120,
                "enabled": True,
            },
            {
                "id": "bad",
                "label": "壞掉的來源",
                "url": "https://example.com/bad.xml",
                "source": "",
                "category": "macro",
                "max_age_hours": 48,
                "extend_age_hours": 120,
                "enabled": True,
            },
        ]

        def fetch(url: str) -> bytes:
            if url.endswith("bad.xml"):
                raise urllib.error.URLError("timed out")
            return SAMPLE_RSS

        items, statuses = generate.gather(feeds, SETTINGS, NOW, fetch)
        self.assertTrue(any(status["ok"] and status["kept"] for status in statuses))
        self.assertTrue(any(not status["ok"] and status["id"] == "bad" for status in statuses))
        self.assertTrue(items)

    def test_dedupe_prefers_direct_link(self):
        google = item(
            title="壽險保費調整方式說明",
            url="https://news.google.com/rss/articles/abc",
            source="經濟日報",
            snippet="",
            category="insurance",
        )
        direct = item(
            title="壽險保費調整方式說明 - 經濟日報",
            url="https://money.udn.com/story/1",
            source="經濟日報",
            snippet="主管機關說明壽險保費調整方式，投保前要先看現金流。",
            category="invest",
        )
        merged = generate.dedupe([google, direct])
        self.assertEqual(len(merged), 1)
        self.assertNotIn("news.google.com", merged[0].url)
        self.assertIn("現金流", merged[0].snippet)
        self.assertEqual(merged[0].category, "insurance")

    def test_source_cap(self):
        titles = ["記憶體族群早盤領漲", "金融股尾盤翻黑", "航運股成交量放大", "鋼鐵原料報價回檔", "塑膠報價轉強"]
        rows = []
        for index, title in enumerate(titles):
            rows.append(
                item(
                    title=title,
                    url=f"https://example.com/{index}",
                    source="鉅亨網",
                    category="invest",
                    published=NOW - timedelta(hours=index + 1),
                )
            )
        rows.append(
            item(
                title="ETF 配息怎麼看才不會只追高",
                url="https://example.com/etf",
                source="中央社",
                category="invest",
                published=NOW - timedelta(hours=3),
            )
        )
        chosen = generate.select_category(rows, "invest", SETTINGS, NOW)
        self.assertLessEqual(len(chosen), 3)
        self.assertEqual(sum(1 for entry in chosen if entry.source == "鉅亨網"), 2)
        self.assertTrue(any(entry.source == "中央社" for entry in chosen))

    def test_extend_window_when_today_is_thin(self):
        fresh = item(title="今天只有一則央行利率消息", url="https://example.com/new", category="macro", published=NOW - timedelta(hours=3), max_age_hours=48, extend_age_hours=200)
        old = item(title="上週央行利率會議的後續影響", url="https://example.com/old", category="macro", published=NOW - timedelta(hours=80), max_age_hours=48, extend_age_hours=200)
        chosen = generate.select_category([fresh, old], "macro", SETTINGS, NOW)
        self.assertEqual({entry.url for entry in chosen}, {fresh.url, old.url})

    def test_commentary_comments_stay_off_the_page(self):
        hidden = generate.prose_to_html("<!-- 不要顯示電話 0912-345-678 -->\n")
        self.assertEqual(hidden, "")
        shown = generate.prose_to_html("第一段說明。\n\n第二段<script>")
        self.assertIn("第一段說明", shown)
        self.assertIn("第二段", shown)
        self.assertIn("&lt;script&gt;", shown)
        self.assertNotIn("<script>", shown)

    def test_page_escapes_title_and_keeps_disclaimer(self):
        edition = {
            "date": "2026-10-28",
            "generated_at": NOW.isoformat(),
            "categories": [
                {
                    "id": "insurance",
                    "name": "保險新聞",
                    "blurb": "保單",
                    "stale_hours": 72,
                    "items": [
                        {
                            "title": "<script>alert(1)</script>",
                            "url": "https://example.com/a?q=1",
                            "source": "中央社",
                            "published_at": NOW.isoformat(),
                            "snippet": "摘要裡不要出現未跳脫的標記 <b>。",
                            "feed_id": "sample",
                        }
                    ],
                }
            ],
        }
        template = (ROOT / "templates" / "layout.html").read_text(encoding="utf-8")
        html_page = generate.page(
            template,
            SETTINGS,
            title='日報 "測試"',
            description="描述",
            canonical="https://show-hsu.github.io/",
            main=generate.render_edition_main(edition, SETTINGS, "<p>關於</p>", "<p>小評</p>", is_home=True),
            current="TODAY",
        )
        self.assertIn("不構成投資建議", html_page)
        self.assertIn("也不是保險招攬", html_page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_page)
        self.assertEqual(html_page.count("<script"), 1)
        self.assertIn("今日小評", html_page)
        self.assertIn("這一天的固定網址", html_page)
        self.assertIn('aria-current="page"', html_page)

    def test_clean_title_strips_site_suffix_and_gossip_is_blocked(self):
        cleaned = generate.clean_title(
            "招銀國際：中國壽險業9月重返正增長 作者 智通財經 - Investing.com 香港",
            "Investing.com 香港 - 股市報價",
            140,
        )
        self.assertEqual(cleaned, "招銀國際：中國壽險業9月重返正增長")
        cleaned = generate.clean_title(
            "台股ETF 逢低可布局- 投資理財- 工商時報",
            "工商時報",
            140,
        )
        self.assertEqual(cleaned, "台股ETF 逢低可布局")
        cleaned = generate.clean_title(
            "獨家/地王瞞不了真相5/壽險公司為何不能長期養地還要看監理",
            "鏡週刊",
            140,
        )
        self.assertTrue(cleaned.startswith("壽險公司"))
        self.assertEqual(generate.clean_source("鏡週刊Mirror Media"), "鏡週刊")
        self.assertEqual(generate.clean_source("TNL The News Lens 關鍵評論網"), "關鍵評論網")

    def test_topic_cap_limits_repeat_briefings(self):
        rows = [
            item(title="楊金龍：匯率走弱時央行採柳樹理論", url="https://example.com/a", source="中央社", category="macro", published=NOW - timedelta(hours=1)),
            item(title="立法院備詢楊金龍重申沒有匯率防線", url="https://example.com/b", source="經濟日報", category="macro", published=NOW - timedelta(hours=2)),
            item(title="楊金龍談外資匯出與明年展望", url="https://example.com/c", source="自由時報", category="macro", published=NOW - timedelta(hours=3)),
            item(title="油價若續漲通膨壓力會再上來", url="https://example.com/d", source="鉅亨網", category="macro", published=NOW - timedelta(hours=4)),
        ]
        chosen = generate.select_category(rows, "macro", SETTINGS, NOW)
        self.assertLessEqual(sum("楊金龍" in entry.title for entry in chosen), 2)
        self.assertTrue(any("油價" in entry.title for entry in chosen))

    def test_images_from_feed_og_and_default(self):
        page = '<meta property="og:image" content="https://img.example.com/story.jpg">'
        self.assertEqual(generate.extract_og_image(page, "https://example.com/a"), "https://img.example.com/story.jpg")
        swapped = '<meta content="https://img.example.com/b.jpg" property="og:image">'
        self.assertEqual(generate.extract_og_image(swapped, "https://example.com/a"), "https://img.example.com/b.jpg")
        generic = '<meta property="og:image" content="https://img.example.com/pic_fb.jpg">'
        self.assertEqual(generate.extract_og_image(generic, "https://example.com/a"), "")
        self.assertFalse(generate.plausible_image("https://cimg.cnyes.cool/static/rss/default/m/06.jpg"))
        self.assertEqual(generate.fetch_og_image("https://example.invalid/nope"), "")

        edition = {
            "categories": [
                {
                    "id": "insurance",
                    "items": [
                        {"title": "有圖", "url": "https://example.com/feed", "image": "https://img.example.com/feed.jpg"},
                        {"title": "要抓", "url": "https://example.com/page", "image": ""},
                        {"title": "失敗", "url": "https://example.com/fail", "image": ""},
                    ],
                }
            ]
        }

        def fetch(url: str) -> str:
            if url.endswith("/fail"):
                raise TimeoutError("slow")
            if url.endswith("/page"):
                return "https://img.example.com/from-og.jpg"
            return ""

        generate.enrich_images(edition, fetch)
        items = edition["categories"][0]["items"]
        self.assertEqual(items[0]["image_source"], "feed")
        self.assertEqual(items[1]["image"], "https://img.example.com/from-og.jpg")
        self.assertEqual(items[1]["image_source"], "og")
        self.assertEqual(items[2]["image"], "/assets/covers/insurance.svg")
        self.assertEqual(items[2]["image_source"], "default")

    def test_card_is_lazy_and_home_has_hero(self):
        edition = {
            "date": "2026-10-28",
            "generated_at": NOW.isoformat(),
            "categories": [
                {
                    "id": "macro",
                    "name": "總經與利率",
                    "blurb": "利率",
                    "stale_hours": 96,
                    "items": [
                        {
                            "title": "央行利率",
                            "url": "https://example.com/rate",
                            "source": "中央社",
                            "published_at": NOW.isoformat(),
                            "snippet": "這是一段足夠放上卡片的利率摘要，用來確認版面。",
                            "feed_id": "sample",
                            "image": "https://img.example.com/rate.jpg",
                        }
                    ],
                }
            ],
        }
        template = (ROOT / "templates" / "layout.html").read_text(encoding="utf-8")
        html_page = generate.page(
            template,
            SETTINGS,
            title="日報",
            description="描述",
            canonical="https://show-hsu.github.io/",
            main=generate.render_edition_main(edition, SETTINGS, "", "", is_home=True),
            current="TODAY",
        )
        self.assertIn('src="/assets/hero.svg"', html_page)
        self.assertIn('src="https://img.example.com/rate.jpg"', html_page)
        self.assertIn('loading="lazy"', html_page)
        self.assertIn('data-fallback="/assets/covers/macro.svg"', html_page)
        self.assertIn("/assets/og.png", html_page)
        for name in ("insurance", "invest", "macro", "retire"):
            self.assertTrue((ROOT / "assets" / "covers" / f"{name}.svg").is_file())

    def test_similar_does_not_merge_up_and_down(self):
        self.assertFalse(generate.similar("台股收盤大漲九百點", "台股收盤大跌九百點"))
        self.assertTrue(generate.similar("台股收盤上漲九百三十九點", "台股收盤上漲九百三十九點並收復四萬七"))

    def test_workflow_contract(self):
        workflow = (ROOT / ".github" / "workflows" / "daily-news.yml").read_text(encoding="utf-8")
        self.assertIn("contents: write", workflow)
        self.assertIn("workflow_dispatch", workflow)
        self.assertIn("0 23 * * *", workflow)
        self.assertIn("--rebuild-only", workflow)
        self.assertTrue((ROOT / ".nojekyll").is_file())
        about = (ROOT / "data" / "about.md").read_text(encoding="utf-8")
        self.assertIn("許欣霈", about)
        self.assertNotRegex(about, r"09\d{2}[-\s]?\d{3}")


if __name__ == "__main__":
    unittest.main()
