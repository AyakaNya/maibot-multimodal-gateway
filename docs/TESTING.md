# Grok 工具決策橋接與圖片輸入（插件 0.2.0）

Gateway Python 86/86、Node 3/3、SDK 2.20.0／2.21.0 各 26/26 插件測試通過。新增以真實子程序 fixture 讀取私有 ACP JSON prompt、驗證圖片區塊、JSON Schema structuredOutput → 工具結果 → 最終回答，及官方 SDK＋本機 Gateway HTTP 的 ContextItem 往返。測試 API-key 環境清除、未宣告工具／錯誤參數／未完成輸出拒絕、遠端 Schema 引用拒絕、無音訊檔入口時明確拒絕且無本機或 API fallback。

工具參數用 Host 已依賴的 jsonschema 驗證。此為 JSON Schema／提示詞橋接，不是原生 API function calling。CLI 原始碼已核對，未使用真實帳號生成、未啟動完整 Host 或連接 QQ；真實圖片理解和 MaiBot 工具執行仍待使用者驗證。依使用者偏好只允許 SuperGrok 訂閱語音，本輪未啟用 Whisper／本機 TTS／付費 API。詳見 [GROK-MULTIMODAL.md](GROK-MULTIMODAL.md)。以下保留歷史記錄。

# MaiBot 1.3.18／SDK 2.20.0 相容修正（插件 0.1.1）

使用者回報實際版本為 MaiBot 1.3.18、SDK 2.20.0。以官方 1.3.18 發佈 commit `2a9af62cec37035d29237acbe2cf3adceb700b27` 的完整 ManifestValidator，在明確 Host／SDK 版本下、未啟用 force compatibility，重現舊 manifest 因 Host 最低 1.3.19 被拒；SDK 範圍僅警告。新版最低 Host 1.3.18／SDK 2.20.0 通過同一校驗器。

插件與安裝 22/22 在隔離的 SDK 2.20.0、2.21.0 環境各通過。新增 1.3.18 原始碼／實例安裝與更新保留設定回歸、1.3.17 拒絕。核對 SDK components、LLMProvider、send、files 介面相同；Host ContextItem／timeout／載入介面已核對。沒有更新使用者核心／SDK，未連接完整 Host 或 QQ、未生成真實媒體。使用者更新後的載入／發送仍待確認。以下保留歷史記錄。

# MaiBot 實例目錄安裝修正

插件／安裝 21/21 通過。新增無 bot.py／pyproject 的實例安裝測試、版本必填與範圍檢查、缺少實例目錄拒絕；確認只新增插件、保留既有 config 與內層程式目錄。官方 `src/common/paths.py` 確認安裝版使用 `maibot run --directory` 與獨立 instance root。沒有在使用者 BSX 目錄操作或啟動 Host；此修正不改插件生成／傳送程式。以下保留歷史記錄。

# MaiBot 插件 0.1.0

目標 MaiBot 1.3.19、maibot-plugin-sdk 2.21.0。插件／安裝 19/19、Gateway Python 80/80、Node 3/3 通過。插件測試在獨立 Python 3.12 venv 使用真實官方 SDK，模擬 Host RPC 與提供者，透過本機 Gateway HTTP 和官方 files.upload 的實際 HTTP PUT 驗證傳輸。

涵蓋新版 ContextItem／舊文字 Provider、manifest 與裝飾器一致、Runner 相對 import 載入、圖片驗證及發送回執、影片檔案作用域缺失先拒絕、送達 unknown 不重試、取消請求不提前釋放槽、非 internal／非允許流拒絕、401、安裝不複製 key、不改核心、更新保留設定與拒絕 symlink。未啟動完整 MaiBot Host 或連接正式 QQ，未使用真實訂閱生成；既有使用者 Gateway 成功回報不代表插件真實聊天傳送已驗證。

以下保留歷史測試記錄。

# Antigravity help stderr 能力探測修正

Python 80/80 通過。以官方 agy 1.4.12 實測 --help：exit 0、stdout 0 bytes、stderr 3048 bytes，--settings 在 stderr。新版限定獨立 --help 探測可合併兩個通道；經實際 run_bounded 探測 session_settings_supported:true。

新增真實子程序 help stderr 回歸、login／prompt／payload 不得使用該模式、正常成功生成不回傳 stderr；舊 help／非選項提及／相似選項不誤判為支援。沒有使用真實帳號生成；這次修復前置能力偵測，不宣稱 Gemini 已生圖成功。以下保留歷史記錄。

# MCP JSONC／BOM 相容與讀取錯誤定位

Python 77/77 通過。官方 CLI 1.1.24 支援 MCP JSONC 註解／尾端逗號，1.3.1 支援 MCP 與 hooks BOM；補上相容解析，且不改寫全域設定。字串中的 URL／comment 字面內容不受影響，解析後仍檢查啟用 MCP。重複鍵、一般 JSON5 與錯誤結構仍阻擋。

新增讀取權限 errno 與格式錯誤行列的去敏分類、128 層深度上限；不再將所有情況合併為 unreadable_or_invalid。使用者實際問題仍待新版離線摘要，沒有把未知設定清空或略過。本輪未生成。以下保留歷史記錄。

# Antigravity 共用擴充離線檢查

Python 71/71 通過。先前 any(value.values()) 與 any(plugins.iterdir()) 會誤擋空 hooks envelope、官方 enabled:false hooks／disabled:true MCP，以及 .DS_Store 等惰性檔案。新增 schema-aware 計數與離線腳本，不輸出設定值，也不執行 CLI 或生成。

測試包含 active 項停止於 CLI 前、未知／畸形／過大／symlink 設定仍阻擋、plugin 雜項與候選目錄區分、共用檔不修改、診斷不含秘密。真實使用者這次阻擋來自哪一類尚待其本機摘要；不宣稱已完成 Gemini 生圖修復。

以下保留歷史記錄。

# Gemini 生圖不再要求全域 strict

Python 64/64 通過。新增缺少／預設／非 strict 全域設定下的生圖本次覆蓋、全域設定不變、原 permissions 規則保留、0600 暫存設定檔、API／Cloud／共享 hook 拒絕、損毀設定拒絕及文字仍要求 strict。舊 CLI 在缺少全域設定時也必須通過 --settings 支援檢查，不會退回全域權限。

使用者已回報 GPT Gateway 生圖成功。Gemini 本次失敗發生於 Gateway 前置設定檢查；修正尚待 Mac 真實 Ultra 生圖驗證，本輪未呼叫服務商。以下保留歷史測試記錄。

# macOS 可信目錄別名與圖片取回

Python 60/60 通過。先以真實本機目錄 symlink 重現 unsafe_media_path，再驗證可信目錄的 ancestor alias／canonical 路徑組合、Codex inline 與 savedPath、artifact_collected 診斷。逐層 dir_fd／O_NOFOLLOW 檢查仍拒絕產物 symlink、越界和 ..；目錄換成 symlink 的競態測試確認讀取 pinned directory，不跟隨外部目標。

使用者的 Codex 原生工具已 completed，但舊 Gateway 尚未成功取圖。本次修正待 Mac 驗證，未使用訂閱重新生成。Node 程式未變更，前次 3/3 結果保留。

以下保留歷史記錄。

# Plus／Ultra 訂閱圖片 runtime 路由

Python 54/54、Node 3/3 通過。新增 11 項測試涵蓋生圖路由、單一並發與失敗不轉 API、Codex 登入類型檢查與原生圖片完成事件、圖片路徑限制、Gemini 本次設定不修改全域設定、舊 CLI 拒絕、當前 session 產物與 stdio timeout 子程序清理。

原生 Codex CLI 0.163.0 在空白 profile 完成 initialize／account/read（未登入），並匯出 schema 核對圖片事件。agy 官方 1.4.12 發行檔 SHA512 校驗通過，help 確認支援本次 --settings 覆蓋。雲端沒有兩家使用者憑證，尚未實測 Plus／Ultra 生成；參見 [完整驗證範圍](SUBSCRIPTION-IMAGES.md)。使用者已另回報 Grok 圖片、影片成功。

以下保留歷史測試紀錄。

# 影片離線診斷與已知實測狀態

Python 43/43、Node 3/3 通過。新增影片 ZDR、圖片引用、原生參數、輪詢／服務端結果分類，離線影片與起始圖片工具區分、成功 session 不誤用舊失敗，以及 CLI duration 6/10 契約測試。未呼叫服務商生成。

使用者回報 macOS 上 Grok CLI 圖片生成成功。影片已提供並呼叫 image_to_video，但 failed，沒有回合上限；當前摘要為 unknown_tool_error，確切原因待使用者執行新版離線診斷。雲端沒有該本機日誌與帳號，不能宣稱影片已修復。

測試通過後雲端執行環境斷線。最終提交透過 GitHub 整合，從固定基底重建相同程式與測試修改；文件於整合中更新。以下保留歷史測試紀錄。

# Grok 媒體模型輪數上限

Python 39/39 通過。新增使用者回報的 available=true、called=false、exit=1、max_turn_requests 場景，現在獨立回報 media_cli_turn_limit_reached；測試有限預算、非法預算拒絕、完成產物在上限退出時仍可回傳。尚未在使用者真實 CLI／訂閱驗證生成。

# 媒體權限規則回歸修正

媒體命令將裸 Edit/Write 改成 macOS 絕對檔案路徑 glob，避免原生 image_gen 被全域 Tool lockdown 誤擋。既有媒體圖／影片測試加入 CLI 參數契約檢查：拒絕 shell、檔案、web/MCP 並保留媒體 allowlist。這是本地測試與官方原始碼核對，不宣稱已實測使用者帳號。

# 工具失敗去敏診斷

Python 36/36 測試通過，新增 HTTP／憑證／本機失敗分類、任意數字不誤判 HTTP、既有 ACP envelope 紀錄離線分析及憑證檔不掃描。未知錯誤仍需使用者本機分類結果，不宣稱已修復上游生成。

# Grok 媒體產物辨識修正

Python 31/31 通過，包含真實子程序在工作目錄寫檔、非零退出保留輸出、事件分批完成、工具未呼叫／失敗區分、其他 session 及模型文字路徑拒絕、去敏診斷。仍需使用者 Mac 的事件紀錄確認此次失敗原因。

# 媒體更新

> Google 登入修正後 Python 25/25 通過；含模擬 agy 程序及共用設定檢查，真實 Mac／帳號仍待驗證，見 [ANTIGRAVITY.md](ANTIGRAVITY.md)。

最新直接媒體傳輸測試：Python 21/21 通過，皆為模擬上游及本地測試；真實 OAuth 媒體尚未驗證，見 [DSH-REVIEW.md](DSH-REVIEW.md)。


Python 16/16 測試通過；新增 Grok 模擬圖片／影片產物及安全驗證。真實訂閱和 Mac 仍未測試，詳見 [MEDIA.md](MEDIA.md)。

# 訂閱 adapter 驗證更新（2026-11-01）

Python 自動測試 11/11 通過（含 loopback HTTP、模擬訂閱 adapter、stdio、timeout cleanup、無 API-key fallback、deny policy 產生及圖片拒絕）。`node tests/chatgpt.test.mjs` 的 3/3 測試通過（plan permission gating、帳號模型檢查、role 轉換、輸出無 credentials）。Node 與 shell 語法檢查通過。

新增程式尚未在 macOS 編譯 Swift helper、安裝 DevKit／CLI 或登入任何真實帳號；目前雲端無 swiftc，也沒有使用者憑證。測試成功不代表 Mac Keychain、官方登入 callback、refresh、CLI 實際 tool denial 或服務商推論已驗證。請執行 docs/MACOS.md 的本機步驟與真實 PoC。

以下保留先前測試記錄：

# 驗證結果

2026-10-30，Python 3.12.14，`python3 -m unittest discover -s tests -v`：5/5 通過。

- 真實 loopback HTTP client → Gateway → 模擬 transport → 文字 response 轉換／圖片 b64 response；驗證固定 xAI 目的端與上游獨立 key。
- 錯誤 Gateway key 回 401；並發滿回 429；訂閱圖片回 403，無上游請求。
- 憑證 0600；放寬為 0644 時拒絕讀取。
- 上游 403 保留拒絕狀態，隱藏錯誤內文，不 fallback。
- OAuth endpoint 拒絕 HTTP／非 auth.x.ai host／userinfo 偽裝。

首次測試受執行沙箱禁止 socket 影響；允許本機 socket 的測試執行後全數通過。

未驗證：服務商實際文字／圖片輸出、真實 OAuth consent/token/refresh、套餐及模型權限、真實 MaiBot 接入。沒有憑證可供測試；shell 代理 `proxy:8080` 也無法連線。原始碼改由 GitHub connector 讀取，未繞過網路代理。圖片端到端目前僅通過模擬上游，真實 PoC 必須配置官方 key 後執行 `scripts/poc.py` 並檢視輸出圖片；不能把測試 fixture 當作實際生成圖片。
