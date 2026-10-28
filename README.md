# Show 的金融保險理財日報

許欣霈（Show）的每日專欄。一天兩到三則和保險、理財有關的新聞，每則是一篇文章：一張圖、用自己的話寫的說明，文末連回原媒體。網站是靜態的，放在 GitHub Pages：<https://show-hsu.github.io>。

不需要付費 API。RSS 只拿來選題，不會再自動把連結清單發布到首頁。

## 怎麼新增一篇

另一個工具只要把下面兩個檔案提交到 `main`，GitHub Actions 就會重畫網站。

```text
posts/2026-10-29/01-foreign-policy.webp
posts/2026-10-29/01-foreign-policy.md
posts/2026-10-29/02-claim-age.webp
posts/2026-10-29/02-claim-age.md
```

一天建議 2 到 3 篇。`01`、`02` 是當天的順序。

### 檔案格式

路徑固定是：

```text
posts/YYYY-MM-DD/NN-slug.md
posts/YYYY-MM-DD/NN-slug.webp
```

- `YYYY-MM-DD` 是台北日期。
- `NN` 是兩位數順序，例如 `01`、`02`。
- `slug` 只用小寫英文、數字和連字號，例如 `claim-age`。
- 圖片跟文章同名，放在同一層。副檔名用 `.webp` 或 `.png`。
- `date` 必須等於資料夾的日期。
- `image` 必須等於圖片檔名。

```markdown
---
title: 外幣保單賣得比較快，先問自己的現金流
date: 2026-10-29
category: 保險
summary: 銷售數字變高，不代表這張保單適合你。先看每個月出不出得來。
image: 01-foreign-policy.webp
source_name: 中央社
source_url: https://www.example.com/story
tags:
  - 外幣保單
  - 現金流
---

這裡用自己的話寫給客戶看，不要貼媒體全文。

## 可以放小標

- 也可以用清單
- 連結只接受 http 或 https，例如 [原文在這裡](https://www.example.com/story)

寫完把 `.md` 和圖片一起推上 `main`。
```

欄位：

| 欄位 | 必填 | 說明 |
| --- | --- | --- |
| `title` | 是 | 文章標題 |
| `date` | 是 | `YYYY-MM-DD`，要和資料夾相同 |
| `category` | 是 | 例如 `保險`、`理財`、`利率`、`退休` |
| `summary` | 是 | 首頁卡片上的一兩句話 |
| `image` | 是 | 同資料夾的圖片檔名 |
| `source_name` | 是 | 原媒體名稱 |
| `source_url` | 是 | 原文章的 http(s) 連結，顯示在文末「新聞來源」 |
| `tags` | 否 | 字串清單。含 `範例` 時，頁面上會標成可替換 |

內文是 Markdown：段落、`##` 小標、`-` 清單、`1.` 清單、`**粗體**`、`*斜體*`、`[文字](https://...)`、`> 引文`。不要寫原始 HTML。

## 頁面

- 首頁是最新一天的文章，每篇一張大圖、標題、摘要、日期，下面才是更早的日子。
- 每篇文章有自己的網址：`/column/YYYY-MM-DD/NN-slug/`。大圖、內文，最後是「新聞來源」。
- 分享到 LINE / Facebook 時，用的是該篇圖片。
- `/archive/` 依日期瀏覽。
- 頁尾說明：內容僅供參考，不構成投資建議，也不是保險招攬。

## 自動發布

`.github/workflows/build-posts.yml` 會在 `main` 上有人推送 `posts/`（以及關於我、模板、樣式）時，重新產生 HTML 並提交。提交訊息帶 `[skip ci]`，避免工作流程一直自己觸發。

這個流程不再用每天早上的 RSS 排程去發布連結頁。

Pages 若已經是 **Deploy from a branch**、`main`、`/ (root)`，不用再改。倉庫維持公開。

若自動提交出現 403：Settings → Actions → General → Workflow permissions 改成 Read and write permissions。

## 選題（不會發布）

想看今天有哪些公開標題，可以在本機跑：

```bash
python3 scripts/fetch_candidates.py
```

它把候選標題印成 JSON，包含標題、來源、連結、時間。失敗的來源會略過。這個指令不寫首頁、也不提交。

## 本機預覽

```bash
python3 -m unittest scripts/test_site.py
python3 scripts/build_site.py
python3 -m http.server 8765
```

關於我的文字在 `data/about.md`。

`legacy/rss-2026-10-28/` 是舊的連結日報資料，網站不再使用。
