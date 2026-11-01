# 訂閱媒體啟用狀態（2026-11-01）

> 更新：新增獨立 `grok-oauth/` 的圖片／編輯及直接影片路徑，與下述 `grok/` CLI 路徑並存，詳見 [DSH-REVIEW.md](DSH-REVIEW.md)。


## 本輪已接入

Grok 官方 Grok Build 的 `image_gen`、`image_to_video` 原生工具。Gateway 已開放兩個路由，實際權限由 CLI 和服務端判斷，沒有抽出／轉送 CLI token、偽裝其他 client、切換帳號或 API-key fallback。

| 訂閱 | 圖片生成 | 圖片編輯 | 影片 | 語音 |
|---|---|---|---|---|
| SuperGrok | 已接入，待真實帳號測試 | 未實作 | 已接入「先生圖再轉影片」，待真實帳號測試 | 未找到已驗證的 headless 音訊介面 |
| ChatGPT Plus / SIWC | 官方明確排除圖片生成工具 | 未支持此整合 | 無已驗證的訂閱介面 | 此流程不支持音訊／影片輸入及轉寫；無已驗證的 TTS 整合 |
| Google AI Ultra / Gemini CLI | 未找到已驗證的 Ultra 額度生圖介面 | 未啟用 | 未找到已驗證的 Ultra 額度介面 | 未找到已驗證的 Ultra 額度介面 |

這是 Gateway 實作狀態，不是三家網頁／App 的功能清單。未接入項目沒有被標成「可用」。HTTP `GET /v1/capabilities`（需 Gateway key）回傳對應狀態，帳號 entitlement 在實測前仍為 not_verified。

## Mac 上使用

安裝與登入沿用 [macOS 說明](MACOS.md)。若已安裝舊版，將新版解壓至新的資料夾，依文件重新 setup、登入；請勿覆蓋或刪除舊版 `.state`。保留舊版可還原，兩版勿同時使用 port 8790。

```bash
python3 -m gateway.app login --provider grok
python3 -m gateway.app serve
```

另開終端執行一筆真實請求：

```bash
python3 scripts/media-poc.py --kind image --prompt '白色桌上的紅蘋果'
python3 scripts/media-poc.py --kind video --prompt '白色桌上的紅蘋果，鏡頭緩慢推近'
```

成功會保存 `artifacts/grok-poc.png|jpg|webp|mp4`。請自行打開確認內容；有檔案與 checksum 不等於媒體內容／時長已通過視覺驗證。

請求格式：

- 圖片：POST `/v1/images/generations`，JSON `{"model":"grok/default","prompt":"...","n":1,"size":"1024x1024"}`。size 可省略，僅轉成 aspect ratio 指示，無精確像素保證。
- 影片：POST `/v1/videos/generations`，JSON `{"model":"grok/default","prompt":"...","duration":6}`，duration 1–15 秒。會先產生起始圖片再動畫化，不接受任意本機檔案或遠端 URL 作輸入。
- 回傳 JSON `data:[{b64_json,media_type,bytes,sha256}]`。影片回傳為本專案的同步 PoC 合約，不是 OpenAI Video API 的非同步 job 合約。
- 共用單一並發；600 秒程序 timeout，忙碌回 429。圖片最多 16 MiB、影片最多 32 MiB；超出會拒絕回傳，已消耗額度不會撤銷。CLI 可能在被終止前已提交生成，不自動重試。
- 語音路由明確回 501；其他訂閱媒體路徑拒絕，不暗中改成付費 API。

## 來源審查

固定 Grok 官方原始碼 commit `2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8`：

- [image_gen](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-tools/src/implementations/grok_build/image_gen/mod.rs)：原生工具呼叫 `/images/generations`，資料含 prompt/model/aspect_ratio/response_format，將圖寫入 session 的 images 目錄；程式對 Free／X Basic 有 SuperGrok 升級限制。
- [video_gen](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-tools/src/implementations/grok_build/video_gen/mod.rs)：提交、輪詢並保存 MP4；帳號限制、ZDR 等限制仍由 CLI 執行。本專案不關閉服務端限制或自動變更隱私設定。
- [media_bearer](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-tools/src/implementations/grok_build/media_bearer.rs)：CLI 自行解析可用 bearer，解析失敗即拒絕。本專案沒有讀取 token。
- [OpenAI Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)：明確說明此訂閱登入流程排除圖片生成工具、音訊／影片輸入、轉寫 API。因此不能把 Plus 登入當成 Images/Audio/Sora API 授權。
- [Google 官方 Gemini CLI Codelab](https://codelabs.developers.google.com/codelabs/quick-guide-to-gemini-cli)：其 Nanobanana 生圖擴充要求 Gemini API key，不能據此宣稱使用 Ultra 訂閱額度。Ultra 在 Gemini/Flow 的權益不等於這條 CLI 路徑的 API 權限。

CLI OAuth 不代表免費或包含無限生成額度；使用量、可能的帳號信用額度與計費以服務商帳號及官方 CLI 顯示為準。Gateway 不提供價格保證。官方 API key 路由維持明確前綴 openai/xai，未自動切換。

## 執行限制與測試

媒體請求僅為允許的 native media tools 開啟 auto-approval，仍限制 allowlist，deny shell／讀寫檔案工具／web／MCP，關閉 subagents、memory、workflow。原生媒體工具本身必須寫入產物，影片工具也會讀取起始圖片；這不是 OS sandbox，無法保證模型完全遵守生成數量、時長及內容指令。僅供受信任的本機使用者，不能公開或接不受信任聊天平台。

產物只接受官方專屬 session 目錄中新出現的一個檔案，不信任模型回覆的任意路徑；拒絕 symlink、超大檔與不符媒體標頭的檔案。多檔或找不到檔案時報錯，不偽造成功。

Python 16/16 測試通過，涵蓋模擬圖／影片產物、權限拒絕、路徑／格式檢查、並發與 timeout；先前 ChatGPT adapter 3/3 測試仍保留。本輪沒有真實 Mac、服務商帳號登入或真實圖片／影片產物，因此不能宣稱已完成真實端到端驗證。三家語音和 ChatGPT/Gemini 訂閱媒體目前仍無法完成啟用。
