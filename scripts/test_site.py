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

    def test_sample_post_builds_without_old_link_list(self):
        posts = build_site.load_posts(ROOT)
        self.assertTrue(any(post["slug"] == "01-sample" for post in posts))
        build_site.build(ROOT)
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        article = (ROOT / "column" / "2026-10-28" / "01-sample" / "index.html").read_text(encoding="utf-8")
        self.assertIn("今天的專欄", home)
        self.assertIn("/posts/2026-10-28/01-sample.webp", home)
        self.assertNotIn("台股ETF上週受益人數", home)
        self.assertNotIn("本日來源", home)
        self.assertIn("新聞來源", article)
        self.assertIn('property="og:image" content="https://show-hsu.github.io/posts/2026-10-28/01-sample.webp"', article)
        self.assertIn('property="og:type" content="article"', article)
        self.assertIn("不構成投資建議", article)
        self.assertIn("也不是保險招攬", article)
        self.assertIn("範例文章", article)

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
