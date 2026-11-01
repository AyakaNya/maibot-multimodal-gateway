# DSH 參考專案再次核對與移植

> 更新：已改用官方 Codex app-server 實作 Plus 生圖與官方 agy CLI 實作 Ultra 生圖，不移植此文的 Codex OAuth 直接 HTTP 路徑。詳見 [最新訂閱圖片指南](SUBSCRIPTION-IMAGES.md)。下文是直接 HTTP 移植的歷史審查。

2026-11-01 重新讀取 HEAD，仍為 `b8023110864494acefc6f5963c2a197d85dda20c`。

之前用 Sign in with ChatGPT（SIWC）限制概括所有 GPT 訂閱路徑不夠精確：SIWC 與 DSH 的 Codex 圖片是不同路徑。應分別判斷，不應因其中一條不支持而宣稱其他條也不可能。

## 實際程式碼證據

| 能力 | DSH 實作／憑證 | 判斷 |
|---|---|---|
| GPT 生圖／編輯 | [image-generate.ts](https://github.com/V1ki/dsh-plugin-subscriptions/blob/b8023110864494acefc6f5963c2a197d85dda20c/src/tools/image-generate.ts#L33)，`chatgpt.com/backend-api/codex/images/generations`、`/edits`；Codex OAuth accessToken、chatgpt-account-id、originator=codex_cli_rs；模型 gpt-image-2 | 插件確實自行實作，並非宿主代呼叫。這不是目前 Gateway 的 SIWC token 路徑；能否讓獨立應用沿用此授權、以及使用者帳號端點權限，尚未完成驗證。沒有把 SIWC token 塞入該端點碰運氣。 |
| Grok 生圖／編輯 | 同檔 38–41 行，`api.x.ai/v1/images/generations`、`/edits`；Grok OAuth Bearer，grok-imagine-image-2.0 | 已移植直接請求格式至獨立 Gateway，不需 DSH 宿主。 |
| Grok 文生影片／圖生影片 | [video-generate.ts](https://github.com/V1ki/dsh-plugin-subscriptions/blob/b8023110864494acefc6f5963c2a197d85dda20c/src/tools/video-generate.ts#L24)，POST `/v1/videos/generations`，GET `/v1/videos/{request_id}`；Grok OAuth Bearer，grok-imagine-video-1.5 | 已移植提交／輪詢／下載，直接文生影片可不先產生起始圖。 |
| 語音／獨立音訊生成 | 工具目錄目前為 image-generate、video-generate、x-search 及 registration，沒有 audio/speech/voice generator | 影片可包含音軌，不等於有獨立 TTS、STT 或即時語音介面。這份來源不能作為語音授權可用的證據。 |

DSH 宿主提供工具註冊、會話、附件保存與前端呈現；圖片及影片的 HTTP 呼叫、OAuth 管理、影片輪詢和下載是插件實作。編輯原圖原本從 DSH attachment store 讀取；Gateway 改由明確提交的 base64 data URL 輸入。

## 這次新增的直接傳輸

在原有官方 CLI 的 `grok/` 路徑以外，新增 `grok-oauth/`：

| Gateway 端點 | 功能 | JSON 欄位 |
|---|---|---|
| POST `/v1/images/generations` | 生圖 | `model:grok-oauth/default,prompt,n:1,size?,quality?` |
| POST `/v1/images/edits` | 編輯 | 前述加 `images:[dataURL,...]`，1–3 張 |
| POST `/v1/videos/generations` | 直接文生影片／圖生影片 | `model:grok-oauth/default,prompt,duration?,aspect_ratio?,resolution?,image?:dataURL` |

影片預設 6 秒、16:9、480p；支援 1–15 秒、480p/720p/1080p。`model` 亦可填寫實際固定媒體模型；不支援未驗證模型猜測或自動換模型。回傳格式沿用本專案 `data[].b64_json,media_type,bytes,sha256`，同步等待，非 OpenAI 非同步 Video API job 合約。

- Bearer 僅送往固定 `api.x.ai` API 原點。
- 簽名影片下載不帶 Bearer，關閉 redirect，只允許 vidgen.x.ai／imgen.x.ai／media.x.ai。其他 CDN host 明確拒絕，需依實際正式來源更新，不會廣泛放行。
- 不讀其他應用或 DSH 的 auth 檔、不抓 cookie、不切帳號；401/403/429 不重試。
- 共用單一並發；輪詢最長 600 秒，單次 HTTP 最長 30 秒。參考圖僅允許 data URL，不接受本機任意路徑／私網 URL；JSON 請求仍限制 1 MiB，測試腳本原圖限制 700 KiB。

## 授權前提：兩條路徑不是共用同一個登入

`grok/`：沿用官方 `grok login` 與官方 CLI 原生媒體工具，目前可直接依 [MEDIA.md](MEDIA.md) 在 Mac 測試。

`grok-oauth/`：使用本 Gateway 自己保存的 OAuth session（既有 `login-grok`）。DSH 使用官方 Grok CLI 的 public client ID；public ID 並非密碼，但程式碼存在、或服務端接受登入，不足以由本次靜態審查證明該 client 允許此獨立應用用途。因此本版沒有直接把 DSH 的 client ID 設成預設。這是正式允許範圍尚待確認，不是宣稱此流程一概違規。

已取得供此 Gateway 使用的核准 client 設定時：

```bash
export GROK_APPROVED_CLIENT_ID='你的核准 client ID'
export GROK_APPROVED_REDIRECT_URI='http://127.0.0.1:你的核准埠/callback'
python3 -m gateway.app login-grok
python3 -m gateway.app serve
```

另開終端：

```bash
python3 scripts/media-poc.py --backend oauth --kind image --prompt '白色桌上的紅蘋果'
python3 scripts/media-poc.py --backend oauth --kind edit --reference-image apple.png --prompt '把蘋果改成綠色'
python3 scripts/media-poc.py --backend oauth --kind video --prompt '鏡頭緩慢掠過森林湖泊'
```

**沒有該 OAuth 設定時，新增直接路徑尚不能登入實測。** 官方 CLI 登入成功不會自動填入 Gateway OAuth session；不用複製 CLI token，先使用 `--backend cli` 的既有路徑。Grok 直接路徑請求成功也只代表該次能力成功，不會授予其他模型、語音或 Gemini 權限。

## 驗證

Python 21/21 測試通過，包括直接圖片／編輯 JSON、純文生影片提交、pending→done 輪詢、request-id URL 編碼、下載不帶 bearer、上游 403 不重試、失敗／逾時、下載 host 限制。這些是模擬上游，沒有使用者 OAuth 憑證，也沒有真實 Mac／服務商生成驗證，不能宣稱此帳號端到端成功。

GPT Codex 圖片授權仍需獨立完成，未硬開；語音沒有從本參考專案找到可移植的 generator。官方 API 仍是明確可選路徑，沒有自動切換。
