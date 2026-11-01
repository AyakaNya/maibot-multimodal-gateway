# Google AI Ultra：Gemini CLI 登入遷移修正

使用者實測收到 `This client is no longer supported for Gemini Code Assist for individuals`。這是個人帳號登入路徑被服務端拒絕，不是密碼錯誤。先前讓 Ultra 使用舊 Gemini CLI 的指引已失效，不能靠重試、改 User-Agent 或借用其他 client ID 修復。

本版 `--provider gemini` / `gemini/模型` 改呼叫官方 Antigravity CLI `agy`，不再呼叫舊 `gemini` 程式。Antigravity 官方說明支援個人 Google 帳號（含 Ultra）登入，並由原生 keyring 管理憑證；headless 使用已快取登入。Gateway 不讀 token 檔、不匯入舊憑證、不自動轉 API key／ADC。

## Mac 使用步驟

1. 下載此修正版到新的資料夾；不要覆蓋或刪除舊 `.state`。新資料夾依 MACOS.md 執行 setup、初始化與重新登入即可。若只需要修 Gemini，可先單獨測試下列 agy 登入。
2. 依 [官方 CLI 安裝說明](https://github.com/google-antigravity/antigravity-cli#installation) 安裝：

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

3. 重開終端，確認 `agy --help` 可用。在新版專案資料夾執行：

```bash
python3 -m gateway.app login --provider gemini
```

4. 使用綁定 Google AI Ultra 的個人 Google 帳號完成瀏覽器登入，不選 API key 或企業 Cloud project。
5. 在 agy 輸入 `/config`，將 **Tool Permission 設為 strict**，然後 `/quit`。這是 agy 的共用設定，會影響其他 agy coding sessions；停止 Gateway 後可自行改回。Gateway 不會自動修改這份共用設定，也不會自動關閉其他已安裝的 hooks／MCP／plugins。
6. 啟動並在另一個終端測試：

```bash
python3 -m gateway.app serve
```

```bash
python3 scripts/subscription-poc.py --provider gemini
```

模型查詢：

```bash
python3 -m gateway.app models --provider gemini
```

## 錯誤排查

- `agy_not_installed`：重開終端後確認 `command -v agy`，依官方安裝指引檢查 PATH。
- `antigravity_set_toolPermission_strict_in_config`：在 agy `/config` 設 Tool Permission=strict；該值保存於 `~/.gemini/antigravity-cli/settings.json`。本程式只讀設定，不修改。
- `antigravity_requires_personal_account_auth`：agy 設定了 `modelProvider` 或企業 `gcp`。先確認要使用個人 Ultra 訂閱，按官方驗證文件切回 account-based authentication；本程式不改動既有設定。
- `antigravity_shared_extensions_require_review`：本機已有非空全域 hooks／MCP／plugins 設定。Gateway 暫停，避免共享的啟動腳本或外部服務被聊天請求觸發。不要直接刪設定；需要先審查並設計隔離方式。本版沒有宣稱此情境已完成接入。
- `subscription_runtime_failed_check_local_login_and_model`：先直接 `agy` 檢查登入是否完成；可在專用空資料夾用官方 `agy -p 'Reply hello' --output-format json` 確認 CLI，模型需由 `agy models` 選擇。

## 與 DSH Antigravity adapter 的差異

參考專案的 `src/providers/antigravity.ts` 使用另一組 Google OAuth scopes、project discovery 與 cloudcode-pa generation transport，不是單純把舊 Gemini CLI 換個名字。本版使用官方 agy CLI，沒有借 client 身份或自動修改 project discovery metadata 以繞過 UNSUPPORTED_CLIENT。

## 驗證範圍

Python 25/25 測試通過：新增原生 agy stream-json 訊息、SUCCESS 結果解析、共用設定不改動、非訂閱路由拒絕及 hooks 檢查。仍未在真實 Mac 安裝 agy 或完成此帳號登入／推論；不能宣稱你的 Google 帳號已恢復服務。圖片、影片與語音支援狀態沒有因這次文字登入遷移而改變。

正式文件：

- [官方 CLI repository 與安裝](https://github.com/google-antigravity/antigravity-cli)
- [Authenticate](https://antigravity.google/docs/install?tab=cli)
- [Headless mode](https://antigravity.google/docs/cli/headless)
- [Permissions](https://antigravity.google/docs/permissions?tab=cli)
- [CLI settings](https://antigravity.google/docs/settings?tab=cli)
