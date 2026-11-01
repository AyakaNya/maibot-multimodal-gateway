# macOS 訂閱登入與文字接入

> 重要修正：本文舊 Gemini CLI 安裝／登入／隔離設定指引已失效；Google AI Ultra 請以 [ANTIGRAVITY.md](ANTIGRAVITY.md) 為準，新版使用 agy 與原生 keyring／共用設定。

> 媒體更新：Grok 圖片與圖片轉影片已新增，最新狀態與命令見 [MEDIA.md](MEDIA.md)；本文後面的舊矩陣只描述最初文字版本。

此版本針對 macOS、ChatGPT Plus、SuperGrok、Google AI Ultra。三家文字 adapter 已實作，但未在真實 Mac／帳號驗證；請先完成下列安裝與 PoC，再判斷帳號是否具備權限。這些方案名稱不是成功授權的證據。

## 1. 準備環境

建議 macOS 14+、Python 3.12+、Node.js 22.12+、Git、Xcode Command Line Tools。若已安裝 Homebrew：

```bash
brew install python@3.12 node git
xcode-select --install
```

Xcode 工具已存在時不用重裝。確認 `python3 --version` 是 3.12 以上；若仍為系統版本，將以下 python3 換成 Homebrew 的 `python3.12`。

在解壓後專案資料夾執行：

```bash
bash scripts/setup-macos.sh
```

腳本下載並固定 OpenAI 官方 DevKit commit `0a36fefeb913055c8c7a1a29b63d82b96b2e841a`、使用其 lockfile 安裝依賴，僅編譯 local SDK，再編譯 Keychain helper。DevKit 目前是 GitHub workspace，不能假設 `npm install @siwc/local` 可用。其 Noncommercial License 適用個人用途；商業發布須另查授權。

另外依 [Grok 官方安裝說明](https://docs.x.ai/build/overview) 安裝 **Grok Build**（不要安裝其他同名套件）。Gemini 使用官方 CLI：

```bash
npm install -g @google/gemini-cli
```

執行 `grok --help`、`gemini --help` 確認 CLI 可用。本輪依官方目前文件撰寫 flags；尚未鎖定／實測特定 CLI binary 版本。若版本不接受 flags，會回錯誤，不移除限制後重試。

## 2. 分別登入

```bash
python3 -m gateway.app login --provider chatgpt
python3 -m gateway.app login --provider grok
python3 -m gateway.app login --provider gemini
```

- ChatGPT：登入 Plus 帳號並允許此本機應用使用方案額度。僅登入身份、未授予 plan usage 不能推論。可能出現 Keychain 存取提示，對本專案 helper 核准即可。
- Grok：官方 `grok login` 打開本機瀏覽器，使用 SuperGrok 帳號。
- Gemini：在 CLI 選 **Sign in with Google**，使用 Google AI Ultra 的 Google 帳號。完成後 `/quit`。不要選 API key 或 Vertex AI。

登入是本機終端互動，不經 HTTP 公開，也不需把 cookie／token 貼到聊天中。若登入過其他 CLI，這裡仍會要求登入：Gateway 使用自己的設定目錄，避免影響既有開發配置。

## 3. 啟動與真實帳號測試

```bash
python3 -m gateway.app serve
```

另開一個終端，在同一專案資料夾逐一執行：

```bash
python3 scripts/subscription-poc.py --provider chatgpt
python3 scripts/subscription-poc.py --provider grok
python3 scripts/subscription-poc.py --provider gemini
```

`default` 是明確選擇官方 runtime 的預設模型；ChatGPT 選擇帳號 SDK 清單中的第一個模型。要固定模型：

```bash
python3 -m gateway.app models --provider chatgpt
python3 scripts/subscription-poc.py --provider chatgpt --model 你的可用模型ID
```

Grok 可從 `GROK_HOME="$PWD/.state/grok" grok models` 查詢。Gemini 使用官方 CLI 模型選擇器確認帳號可用型號。失敗時先保留終端顯示的 Gateway error code，不分享 `.state`；沒有自動切 API key 的行為。

Gateway 仍為 `http://127.0.0.1:8790/v1`，使用 `.state/gateway.key` 的獨立密鑰。`POST /v1/chat/completions` 模型前綴為 `chatgpt/`、`grok/`、`gemini/`；只支援字串文字與 `stream:false`。CLI 路徑把完整歷史作 JSON conversation 交給模型，不保證與原生 Chat Completions 的 role 語義完全相同。

## 安全與限制

- ChatGPT：官方 SDK 處理 PKCE、身份驗證、動態 client、scope、refresh 與模型發現。此專案 AES-GCM 加密 credentials，32-byte key 存 macOS Keychain；key 不經 argv 或 stdout。Keychain 鎖住／遺失時失敗，不退回明文。
- Grok：`GROK_HOME=.state/grok`，官方 CLI 管理 OAuth 與刷新；原生憑證保護由 CLI 負責，不宣稱全部使用 Keychain。停用 API-key auth、Claude/Codex/Cursor 設定匯入與 workflow；空工具 allowlist 並 deny shell／檔案／web／MCP，停用 subagents、memory。
- Gemini：`GEMINI_CLI_HOME=.state/gemini`，官方 CLI 管理帳號與刷新；關閉 hooks、extensions 與 MCP 設定，使用 priority 999 deny-all policy。
- 專屬目錄 0700、設定 0600；CLI 自己建立的 credential 檔案依其實作。推論在新的私人暫存工作目錄進行，提示詞不放 argv、不印上游 stderr；150 秒 timeout、輸出上限約 2 MiB、單一並發。
- 工具限制是 CLI 設定，並非 OS sandbox。企業管理政策或 CLI 版本可能改變行為；本輪尚未在 Mac 測試實際工具拒絕效果。不要把本服務公開或連正式 QQ。
- 訂閱圖片／編輯、語音、影片全部未驗證且未啟用。官方 API 圖片 PoC 仍保留，僅使用明確 `openai/`、`xai/` 前綴時才會使用 API key。

## 支援矩陣

| 方案 | 登入／文字實作 | 本機真實帳號 | 訂閱圖片／音訊／影片 |
|---|---|---|---|
| ChatGPT Plus | 官方 SIWC SDK + Keychain adapter | 待測 | 未啟用 |
| SuperGrok | 官方 Grok Build CLI bridge | 待測 | 未啟用 |
| Google AI Ultra | 官方 Gemini CLI bridge | 待測 | 未啟用 |

官方來源：[OpenAI DevKit](https://github.com/openai/sign-in-with-chatgpt-devkit)、[OpenAI 登入](https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt)、[Grok headless](https://docs.x.ai/build/cli/headless-scripting)、[Grok config 原始碼文件](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/26-config-reference.md)、[Gemini 登入](https://geminicli.com/docs/get-started/authentication/)、[Gemini policy](https://geminicli.com/docs/reference/policy-engine/)。
