# 訂閱媒體啟用狀態（2026-11-01）

> 最新：使用者回報 Grok 圖片與影片成功。Plus／Ultra 已新增官方 runtime 圖片 adapter，帳號待測；最新指令與矩陣以 [訂閱生圖指南](SUBSCRIPTION-IMAGES.md) 為準。以下保留原先各輪審查／診斷紀錄。

> 更新：新增獨立 `grok-oauth/` 的圖片／編輯及直接影片路徑，與下述 `grok/` CLI 路徑並存，詳見 [DSH-REVIEW.md](DSH-REVIEW.md)。


## 本輪已接入

Grok 官方 Grok Build 的 `image_gen`、`image_to_video` 原生工具。Gateway 已開放兩個路由，實際權限由 CLI 和服務端判斷，沒有抽出／轉送 CLI token、偽裝其他 client、切換帳號或 API-key fallback。

| 訂閱 | 圖片生成 | 圖片編輯 | 影片 | 語音 |
|---|---|---|---|---|
| SuperGrok | 使用者回報 CLI 生圖成功 | 未實作 | 使用者調整 ZDR 設定後回報 CLI 影片成功 | 未找到已驗證的 headless 音訊介面 |
| ChatGPT Plus / Codex | 已接入原生 image_gen，帳號待測 | 未接入本路由 | 未接入 | 未接入 |
| ChatGPT Plus / SIWC | 官方明確排除圖片生成工具 | 未支持此整合 | 無已驗證的訂閱介面 | 此流程不支持音訊／影片輸入及轉寫；無已驗證的 TTS 整合 |
| Google AI Ultra / Antigravity CLI | 已接入原生 generate_image，帳號待測 | 未接入本路由 | 未接入 | 未接入 |

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
- 影片：POST `/v1/videos/generations`，JSON `{"model":"grok/default","prompt":"...","duration":6}`，CLI image_to_video 的 duration 僅接受 6 或 10 秒（獨立 OAuth 接口的契約不同）。會先產生起始圖片再動畫化，不接受任意本機檔案或遠端 URL 作輸入。
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

## 修正：圖片回傳 missing_or_ambiguous

舊版 `media_artifact_missing_or_ambiguous_check_cli_entitlement` 只代表檔案數量不是一，不能作為帳號無權限的結論。舊版忽略 CLI 工具輸出，並在收集圖片之前刪除 CLI 的暫存工作目錄。

新版改讀官方 `streaming-json` 的 tool_call/tool_call_update，追蹤實際原生工具是否完成；保留當次工作目錄直到讀取媒體完成，並只接受本次 session UUID 或私人工作目錄內的產物。工具路徑／完成狀態分批到達也能處理。不接受模型自然語言宣稱的任意檔案路徑，不擴大到掃描整台 Mac。

若 CLI 因達到 turn 上限以非零退出，但原生工具已回報完成且唯一媒體檔案有效，仍可回傳已成功生成的媒體；不自動重新生成或重試服務商請求。

更新：停止 Gateway（Ctrl+C），`git pull --ff-only`，重新 `python3 -m gateway.app serve`，再執行圖片 PoC。仍失敗時，請檢查新版錯誤碼：

- `media_cli_tool_not_available`：CLI 可用工具清單未包含所需媒體工具。
- `media_cli_tool_not_called`：模型沒有呼叫所需工具，不能據此判定訂閱權限。
- `media_cli_tool_failed`／`media_cli_tool_not_completed`：工具失敗或沒有完成。
- `media_cli_output_file_not_found`：工具回報完成，但允許的目錄沒有可讀產物。
- `media_multiple_artifacts`：出現多個候選產物，不任意挑一張。
- `media_cli_stream_format_unsupported`：回傳格式不符合目前官方 CLI streaming-json。

可分享以下診斷輸出及 `grok version`；不要分享其他憑證檔：

```bash
cat .state/media-diagnostic.json
grok version
```

該診斷檔僅包含固定欄位的階段、工具名稱、布林值、計數、程序退出碼及已知 stop reason，不記錄提示詞、模型文字、token、簽名 URL 或檔案路徑，檔案權限 0600。這次修正通過本地模擬與真實子程序測試；尚無使用者 Mac 的事件紀錄，實際失敗原因仍待本機新診斷確認。

### 工具有呼叫，但 tool_failed

若摘要為 `tool_advertised=true`、`tool_called=true`、`tool_failed=true`，可確認 CLI 工具本身失敗，但不能從這些布林值判斷原因。`exit_code=0` 只代表 CLI 回合正常結束，不代表 image_gen 成功。

新版摘要 version=2 增加 `failure.category`、`http_statuses` 與固定白名單的 `error_codes`，從工具失敗輸出提取，不保存原始錯誤文字。401／403／429、非 xAI 登入、缺少媒體憑證、本機權限、參數和網路錯誤分別分類；未知內容明確為 unknown_tool_error，不猜測套餐問題。

**優先診斷既有失敗，不重新生圖：**

```bash
git pull --ff-only
python3 scripts/media-diagnostic.py
```

此命令不連網、不呼叫 grok、不消耗生成額度。它只在本專案 `.state/grok/sessions` 中找近期有界的 `updates.jsonl`，讀取圖片工具失敗事件並輸出同樣去敏的分類；不讀 auth/token 檔或輸出原始對話。如果 `found=false`，可能是當前 CLI 沒保存相容格式的更新紀錄，不能據此推斷權限。

若版本 1 診斷來自舊流程，離線命令可在有相容紀錄時補出原因。需要新請求時再重啟 Gateway，從 `.state/media-diagnostic.json` 讀 version=2。尚無使用者實際錯誤內容，因此本輪是補齊診斷，並非宣稱服務商失敗已解決。

### 修正：Gateway 自己的 Edit/Write 全域拒絕會擋住原生媒體工具

使用者 Grok 1.0.70 的圖片呼叫回報工具已提供、已呼叫，但本機 permission denied。核對官方原始碼後，發現 Gateway 的媒體命令包含 `--deny Edit`、`--deny Write`，是確定的設定錯誤：

- [permission_access.rs](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-tools/src/permission_access.rs) 將 ImageGen 映射為 `AccessKind::Tool("image_gen")`，而非檔案 Edit。
- [policy.rs 的 rule_reaches](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-permission-rules/src/policy.rs) 明確將工具範圍的 Edit deny/ask 套用到原生 Tool；檔案路徑 pattern 則不會。
- [rules.rs](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-permission-rules/src/rules.rs) 將 Write 視為 Edit 的別名。`Edit(*)`／`Write(*)` 同樣是全域規則，不能作為修正。

媒體命令已改用 `--deny 'Edit(/**)' --deny 'Write(/**)'`，在目前目標 macOS 上拒絕一般檔案路徑修改；保留 `--deny Bash`、Read、Grep、WebFetch、MCPTool，以及 `--tools image_gen`（影片為 image_gen,image_to_video）的明確 allowlist。文字路徑維持原本工具全禁規則。

此變更只修正本 Gateway 建立的過廣規則，不移除服務商／管理員限制、不更換憑證、不改走付費 API。回歸測試檢查媒體命令沒有裸 Edit/Write／(*) lockdown，且檔案、shell 與網路／MCP 限制仍在。尚未在使用者 Mac 上實際生成，需更新後重啟並測試；如果還有其他拒絕，仍按新版診斷分別處理。

```bash
# 在第一個終端 Ctrl+C 停止舊 Gateway，再執行：
git pull --ff-only
python3 -m gateway.app serve
```

```bash
# 另一個終端：
python3 scripts/media-poc.py --backend cli --kind image --prompt '白色桌上的紅蘋果'
```

### 修正：max_turn_requests 在圖片工具尚未呼叫前退出

使用者回報 `exit_code=1, tool_advertised=true, tool_called=false, stop_reason=max_turn_requests`。舊設定生圖 `--max-turns 2`、影片 `--max-turns 3` 過於緊縮，而且錯誤分類先回報 tool_not_called，掩蓋了真正的停止條件。

[官方 headless 文件](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-pager/docs/user-guide/14-headless-mode.md) 說明該上限計算 main-agent model rounds，而不是生成圖片數。新版預設生圖 8 輪、影片 12 輪；仍有限，保留單一程序、600 秒 timeout、工具 allowlist、檔案路徑 deny、shell／web／MCP deny 及不切換 API key。

如需自行控制預算，可在啟動 Gateway 的同一終端設定 `GATEWAY_GROK_MEDIA_MAX_TURNS`，只接受 1–16 的整數；未設定採上述預設。增加模型輪數可能增加訂閱使用量，不代表只會消耗一張圖片的額度；CLI 代理仍非固定參數的直接 API 呼叫。Gateway 不因上限錯誤再啟動第二次生成，提示也明確要求媒體工具失敗時停止。

碰到上限且沒有完成產物，現在回 `media_cli_turn_limit_reached`，不是 tool_not_called；有原生工具已完成且媒體有效的情況仍回傳該產物。診斷增加 `configured_turn_budget`、`turn_limit_reached`、`usage_event_count` 與 `other_tool_call_count`，不保存提示詞或任意工具名稱。usage event 數量不等同精確模型輪數。

更新後需先 Ctrl+C 停止舊 Gateway、`git pull --ff-only`、重新 `python3 -m gateway.app serve`，才會採用新上限。不需重新登入。該記錄不能證明模型為何在前幾輪沒有呼叫 image_gen，也不能保證提高上限即一定生圖成功；本輪修正的是過低預設及誤分類，不宣稱帳號權限已通過。


## 圖片成功、影片工具失敗的離線診斷

使用者已回報圖片生成成功。最新影片紀錄是 image_to_video 已提供、已呼叫、failed，退出碼 0、end_turn，沒有碰到回合上限。這只確認原生工具執行失敗，不能推斷為帳號不支援或已確定 ZDR 限制。

更新後直接分析既有紀錄，不需要重啟 Gateway 或重新生成：

```bash
git pull --ff-only
python3 scripts/media-diagnostic.py --kind video
```

命令只掃描本專案 CLI 的 updates.jsonl，輸出固定分類、狀態及代碼；不輸出提示詞、圖片路徑、簽名 URL、token 或原始錯誤。會停在最近一個含指定工具的 session；最近成功時不會回報更舊的失敗。found=false 表示未找到可用的失敗紀錄，並不代表影片權限已確認。

按上述固定官方 video_gen 原始碼補上：

| failure.category | 意義與下一步 |
|---|---|
| video_zdr_storage_required | CLI 明確回報 ZDR 需要儲存配置。保留現有隱私設定，依官方 ZDR storage 文件檢查是否具備可配置的 user-hosted bucket；Gateway 不會自動關閉隱私模式。 |
| video_source_image_invalid | 起始圖片引用無法讀取或格式不符；檢查 Gateway 與 CLI 的圖片傳遞。 |
| invalid_tool_arguments | 原生工具參數不符；image_to_video duration 僅接受 6/10。此次 PoC 預設 6，本次收緊驗證不代表已修復使用者的失敗。 |
| video_poll_timeout / video_request_expired | 影片輪詢超時或請求到期。 |
| video_server_generation_failed / video_response_incomplete | 服務端生成失敗或缺少必要結果。 |
| unknown_tool_error | 既有訊息仍不足以分類；不能將它當作權限判定。 |

本輪只補上診斷及符合 CLI 的秒數驗證，未宣稱影片問題已解決，也不自動重試或轉 API key。
