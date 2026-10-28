# Show 的金融保險理財日報

許欣霈（Show）的個人品牌網站。每天自動整理公開的金融、保險、理財新聞標題，做成一份給客戶看的靜態日報，放在 GitHub Pages：<https://show-hsu.github.io>。

不需要付費 API，也不需要 API 金鑰。新聞只留標題、來源、台北時間、RSS 提供的短摘要、一張縮圖，以及原文連結。不轉載全文。

## 合併之後要做的一次設定

GitHub 不會在你按下合併時自動打開 Pages。請到這個倉庫：

1. **Settings → Pages → Build and deployment → Source** 選 **Deploy from a branch**。
2. Branch 選 **`main`**，資料夾選 **`/ (root)`**，按 Save。
3. 倉庫要維持 **Public**。免費帳號的 GitHub Pages 需要公開倉庫。

請不要改成「GitHub Actions」當 Pages 來源。這個網站是把產生好的 HTML 提交進 `main`，再由分支直接供檔。選成 Actions 的話，每天的更新不會出現在網站上。

第一次打開之後，通常一兩分鐘內就可以從 <https://show-hsu.github.io> 看到首頁。根目錄有 `.nojekyll`，Pages 會照原檔送出，不會再跑 Jekyll。

若每天的 Action 在 `git push` 時出現 403：

到 **Settings → Actions → General → Workflow permissions**，改成 **Read and write permissions**。工作流程檔裡已經寫了 `contents: write`。若之後對 `main` 打開分支保護、又不允許 GitHub Actions 推送，日報就無法自動更新。

## 每天怎麼更新

`.github/workflows/daily-news.yml` 會：

- 排程：UTC 23:00，也就是台北時間早上 7:00。GitHub 的排程偶爾會晚幾分鐘到幾十分鐘。
- 手動：Actions 頁面的「每日新聞」→ Run workflow。
- 你改了 `data/commentary/`、`data/about.md`、模板或樣式並推上 `main` 時，只依現有新聞重畫頁面，不重抓 RSS。

單一來來源抓失敗會略過，整份日報仍會產生。若全部失敗、或有效新聞少於 6 則，工作流程會失敗，並保留上一版，不會把首頁蓋成空白。

產生程式只使用 Python 標準庫。

## 新聞從哪裡來

設定在 `config/feeds.json`，分類與則數在 `config/settings.json`。目前有接上、而且實際回過項目的來源：

- Google 新聞 RSS（`hl=zh-TW&gl=TW&ceid=TW:zh-Hant`）：保險、壽險、金管會、宣告利率、央行利率、匯率、退休、稅務、台股、理財
- 中央社財經：<https://feeds.feedburner.com/rsscna/finance>
- 自由時報財經：<https://news.ltn.com.tw/rss/business.xml>
- 經濟日報：<https://money.udn.com/rssfeed/news/1001/5591?ch=money>
- 鉅亨網頭條與台股
- Yahoo 財經：<https://tw.news.yahoo.com/rss/finance>

工商時報、中時的部分 RSS 會回 403，ETtoday 與今周刊會回網頁而不是 RSS，聯合新聞網財經 RSS 是空的，這些沒有放進清單。之後若某個網址失效，那一條會被略過，狀態寫在 `data/editions/日期.json` 的 `feed_status`。

分類是：保險新聞、理財投資、總經與利率、退休與稅務。同一則報導只留一次，每個分類最多 8 則，同一媒體最多 3 則。

## 圖片

每一則都有一張 16:9 的縮圖，手機上會延遲載入（`loading="lazy"`）：

1. 先用 RSS 的 `media:thumbnail`、`media:content` 或 `enclosure` 圖片。
2. 沒有的話，才去原文頁看 `og:image`（逾時 4 秒，只讀頁面前段）。失敗、逾時、或明顯是全站預設圖（例如檔名含 `logo`、`pic_fb`）就放棄。
3. 還是沒有，就用 `assets/covers/` 裡該分類的原創插圖。遠端圖片若後來壞掉，瀏覽器會自動改顯示這張插圖。

這些插圖與首頁橫幅 `assets/hero.svg` 是這個網站自己畫的，不是圖庫照片。分享到 LINE / Facebook 用的是 `assets/og.png`（1200×630）。日報不會把媒體照片下載進倉庫。

## 今日小評

每一天可以有一則短評，檔名就是日期：

```text
data/commentary/2026-10-28.md
```

說明與空白範本在 `data/commentary/README.md`。檔案若是空的，或整段都包在 `<!-- 註解 -->` 裡，網站就不會出現小評。寫上文字、推上 `main` 之後，頁面會重畫，不會重抓新聞。

請不要貼媒體全文，也不要寫客戶姓名、電話或其他個資。推上去之後就是公開的。

## 關於我

首頁和「關於」頁的文字來自 `data/about.md`。註解不會顯示。請改成你自己的話。不要留下電話，或未經你確認的證照字號、年資、得獎紀錄。

## 本機預覽

```bash
python3 -m unittest scripts/test_generate.py
python3 scripts/generate.py
python3 -m http.server 8765
```

只改小評、不想重抓新聞時：

```bash
python3 scripts/generate.py --rebuild-only
```

要重畫分享圖 `assets/og.png` 才需要 Pillow，每天的自動更新不用。

## 目錄

| 路徑 | 用途 |
| --- | --- |
| `scripts/generate.py` | 抓 RSS、挑新聞、寫 HTML |
| `config/` | 來源與分類 |
| `templates/layout.html` | 頁面外框與免責聲明 |
| `assets/style.css` | 樣式 |
| `assets/hero.svg` | 首頁橫幅 |
| `assets/og.png` | 分享預覽圖 |
| `assets/covers/` | 四個分類的預設插圖 |
| `data/editions/` | 每天留下的新聞 JSON |
| `data/commentary/` | 今日小評 |
| `data/about.md` | 關於我 |
| `index.html` | 今天的日報 |
| `archive/` | 彙整與每一天的固定網址 |

## 免責

新聞來自當日頁面上所列媒體的公開 RSS，本站只做整理。內容僅供參考，不構成投資建議，也不是保險招攬。
