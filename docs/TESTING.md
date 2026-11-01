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
