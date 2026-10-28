#!/usr/bin/env python3
"""專欄建置的離線測試。"""

from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402
import fetch_candidates  # noqa: E402
import fetch_source_image  # noqa: E402

SAMPLE = """---
title: 保費怎麼看
date: 2026-10-28
category: 保險
summary: 先看自己扛不扛得住。
image: 01-premium.webp
source_name: 中央社
source_url: https://example.com/story
tags:
  - 保費
  - 範例
---

先看現金流。

## 可以想的一件事

- 這筆保費每個月出不出得來
- 不是只看報酬率

詳見 [原文](https://example.com/story)。
"""


class SiteTests(unittest.TestCase):
    def test_front_matter_and_markdown(self):
        meta, body = build_site.parse_front_matter(SAMPLE)
        self.assertEqual(meta["title"], "保費怎麼看")
        self.assertEqual(meta["tags"], ["保費", "範例"])
        html_body = build_site.render_markdown(body)
        self.assertIn("<h3>可以想的一件事</h3>", html_body)
        self.assertIn("<li>這筆保費每個月出不出得來</li>", html_body)
        self.assertIn('href="https://example.com/story"', html_body)
        self.assertNotIn("<script>", build_site.render_markdown("小心 <script>alert(1)</script>"))
        self.assertIn("&lt;script&gt;", build_site.render_markdown("小心 <script>alert(1)</script>"))
        rewritten = fetch_source_image.update_front_matter(SAMPLE, "01-premium.webp", "圖片來源：中央社")
        self.assertTrue(rewritten.endswith(body))
        self.assertIn('image_credit: "圖片來源：中央社"', rewritten)
        self.assertTrue(fetch_source_image.is_generic_url("https://imgcdn.cna.com.tw/www/images/pic_fb.jpg"))
        self.assertFalse(fetch_source_image.is_generic_url("https://cdn.example.com/news/story-photo.jpg"))

    def test_today_posts_build_three_cards(self):
        posts = build_site.load_posts(ROOT)
        categories = {post["category"] for post in posts}
        self.assertTrue({"理財投資", "保險新聞"} <= categories)
        self.assertFalse(any(post["slug"] == "01-sample" for post in posts))
        build_site.build(ROOT)
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(home.count('class="feature-card"'), 3)
        self.assertNotIn("01-sample", home)
        self.assertNotIn("台股ETF上週受益人數", home)
        self.assertNotIn("本日來源", home)
        for post in posts:
            article = (ROOT / "column" / post["date"] / post["slug"] / "index.html").read_text(encoding="utf-8")
            self.assertIn(post["image_url"], article)
            if post.get("image_credit"):
                self.assertIn(post["image_credit"], article)
            self.assertIn("新聞來源", article)
            self.assertIn(post["source_url"], article)
            self.assertIn('property="og:type" content="article"', article)
            self.assertIn("不構成投資建議", article)
            self.assertIn("也不是保險招攬", article)

    def test_workflow_publishes_posts_not_rss(self):
        workflow = (ROOT / ".github" / "workflows" / "build-posts.yml").read_text(encoding="utf-8")
        self.assertIn("posts/**", workflow)
        self.assertIn("[skip ci]", workflow)
        self.assertNotIn("cron:", workflow)
        self.assertIn("contents: write", workflow)
        self.assertFalse((ROOT / ".github" / "workflows" / "daily-news.yml").exists())

    def test_fetch_candidates_prints_json_and_skips_failures(self):
        feeds = [
            {"id": "good", "label": "好的", "url": "https://example.com/good.xml", "source": "中央社", "enabled": True},
            {"id": "bad", "label": "壞的", "url": "https://example.com/bad.xml", "source": "", "enabled": True},
        ]
        xml = """<?xml version="1.0"?><rss><channel><item>
        <title>外幣保單銷售增加</title>
        <link>https://example.com/a</link>
        <pubDate>Wed, 28 Oct 2026 07:00:00 GMT</pubDate>
        <source>中央社</source>
        </item></channel></rss>""".encode()

        def fetch(url: str) -> bytes:
            if url.endswith("bad.xml"):
                raise urllib.error.URLError("timed out")
            return xml

        report = fetch_candidates.collect(feeds, fetch)
        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(report["candidates"][0]["title"], "外幣保單銷售增加")
        self.assertEqual(report["errors"][0]["id"], "bad")
        encoded = json.dumps(report)
        self.assertNotIn("index.html", encoded)


if __name__ == "__main__":
    unittest.main()
