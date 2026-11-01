# MaiBot Multimodal Gateway

供 macOS 本機單使用者使用的獨立 Gateway，研究及接入 ChatGPT Plus、SuperGrok、Google AI Ultra。僅監聽 `127.0.0.1:8790`，需要獨立 Gateway key；不修改 MaiBot 核心、不接正式 QQ、不依賴 DSH 宿主。

**目前為原型。** 使用者已回報 macOS／SuperGrok 官方 CLI 圖片生成成功；影片在使用者調整 ZDR 設定後也回報成功。使用者也已回報 GPT Plus 生圖成功；Ultra 訂閱圖片路由已實作，仍待使用者帳號驗證；程式測試使用模擬上游。

## 功能狀態

| 路由／登入方式 | 文字 | 圖片 | 影片 | 語音 |
|---|---|---|---|---|
| ChatGPT 官方 Sign in with ChatGPT | adapter 已實作 | 此 SIWC 路徑不支援 | 未接入 | 未接入 |
| ChatGPT Plus → 官方 Codex app-server | 沿用 SIWC 文字路由 | 原生 image_gen，使用者回報成功 | 未接入 | 未接入 |
| Grok 官方 CLI | adapter 已實作 | 原生 image_gen，使用者回報成功 | 先生圖再 image_to_video，使用者回報成功 | 未接入 |
| Grok 獨立核准 OAuth session | 已實作 | 直接生成／編輯 | 直接文生／圖生影片 | 未接入 |
| Google AI Ultra → 官方 Antigravity CLI `agy` | adapter 已實作 | 原生 generate_image 已接入，帳號待測 | 未驗證 | 未驗證 |
| OpenAI／xAI 官方 API key（明確選用） | 已實作 | 生成已實作 | 未接入 | 未接入 |

Google 個人訂閱登入已改接 `agy`，**不要再安裝舊 Gemini CLI 或嘗試舊個人 Code Assist 登入**。`--provider gemini` 為相容命名，實際執行 `agy`。詳見 [Antigravity 遷移](docs/ANTIGRAVITY.md)。

## macOS 安裝

需要 Python 3.12+、Node.js 22.12+、Git 及 Xcode Command Line Tools。若已有 Homebrew：

```bash
brew install python@3.12 node git
xcode-select --install
```

若 Xcode 工具已安裝不用重裝。確認 `python3 --version` 為 3.12 以上。

```bash
git clone https://github.com/AyakaNya/maibot-multimodal-gateway.git
cd maibot-multimodal-gateway
bash scripts/setup-macos.sh
```

setup 會下載並編譯固定版本的 OpenAI 登入 DevKit，再建立 macOS Keychain 加密 helper。第三方依賴不包含在本倉庫，須遵守各自授權；OpenAI DevKit 為非商業授權，商業使用需另確認。

按 [Grok 官方說明](https://docs.x.ai/build/overview) 安裝 Grok Build。Google 個人訂閱使用 [官方 Antigravity CLI](https://github.com/google-antigravity/antigravity-cli)：

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

安裝後重開終端，確認 `grok --help`、`agy --help` 可用。

## 登入及啟動

只登入你需要的服務：

```bash
python3 -m gateway.app login --provider chatgpt
python3 -m gateway.app login --provider grok
python3 -m gateway.app login --provider gemini
```

Google 登入使用綁定 Ultra 的個人帳號。文字路由需在 agy `/config` 設 **Tool Permission = strict**，然後 `/quit`；生圖路由使用本次設定覆蓋，不要求更改全域權限。這是 agy 共用設定，會影響其他 agy sessions；Gateway 不會替你修改。全域 hooks／MCP／plugins 會先做去敏檢查；空設定、明確停用的 hooks／MCP 與 plugins 雜項檔案不再誤擋。碰到 shared_extensions_require_review 時先執行 `python3 scripts/antigravity-diagnostic.py`，不會啟動 CLI 或生成；詳見 [訂閱生圖指南](docs/SUBSCRIPTION-IMAGES.md)。

```bash
python3 -m gateway.app serve
```

另開終端，在相同專案資料夾執行：

```bash
python3 scripts/subscription-poc.py --provider chatgpt
python3 scripts/subscription-poc.py --provider grok
python3 scripts/subscription-poc.py --provider gemini
python3 scripts/media-poc.py --backend cli --kind image --prompt '白色桌上的紅蘋果'
python3 scripts/media-poc.py --backend cli --kind video --prompt '森林湖泊，鏡頭緩慢前進'
```

媒體成功後保存至 `artifacts/`。Grok 直接 OAuth 路徑另需核准 client／redirect 設定，不能直接共用 CLI token；見 [DSH 直接媒體移植](docs/DSH-REVIEW.md)。不會自動切帳號、改模型或切換 API-key 計費。實際額度與計費由服務商決定。

## Plus／Ultra 訂閱生圖

已新增官方 Codex 與 agy 原生圖片 adapter；不使用 API key。更新並重啟 Gateway 前，先完成圖片登入：

```bash
npm install -g @openai/codex
python3 -m gateway.app login-images --provider chatgpt
python3 -m gateway.app login-images --provider gemini
```

保持 Gateway 運行，另開終端：

```bash
python3 scripts/media-poc.py --provider chatgpt --kind image --prompt '白色桌上的紅蘋果'
python3 scripts/media-poc.py --provider gemini --kind image --prompt '白色桌上的紅蘋果'
```

Codex 圖片登入與原 SIWC 文字登入分開。Gemini 使用新版 agy 的本次設定覆蓋，不要求全域 strict，也不修改全域設定。完整更新／登入／呼叫與限制見 [訂閱生圖指南](docs/SUBSCRIPTION-IMAGES.md)。

## 更新

停止 Gateway（Ctrl+C），在專案資料夾執行：

```bash
git pull --ff-only
```

若更新說明要求重新建置 OpenAI adapter，再執行 `bash scripts/setup-macos.sh`。`.state/`、`.vendor/`、產物及本機環境設定均不進 Git；不要手動提交或分享。

## HTTP 介面

所有端點需要 `Authorization: Bearer <Gateway key>`；key 保存在本機 `.state/gateway.key`，不會在初始化時印出。

- `GET /health`、`GET /v1/capabilities`
- `POST /v1/chat/completions`：`model` 前綴 `chatgpt/`、`grok/`、`gemini/`；文字 `messages`，僅 `stream:false`，無 tool calls。
- `POST /v1/images/generations`：訂閱 runtime 用 `grok/default`、`chatgpt/default`、`gemini/default`；獨立 OAuth 用 `grok-oauth/default`。
- `POST /v1/images/edits`：獨立 Grok OAuth，參考圖以 base64 data URL 明確提交。
- `POST /v1/videos/generations`：同步 PoC，回傳 base64 MP4，非 OpenAI 非同步 Video API job 合約。
- 音訊路由明確拒絕，沒有假裝成功的空介面。

原生 CLI 的多輪歷史以 JSON conversation 輸入，與原生 Chat Completions role 語義不完全相同。CLI 工具權限限制不是完整 OS sandbox，僅供受信任本機使用者；不要反向代理公開服務。

## MaiBot 插件

已新增獨立 Host/Runner 插件，目標 MaiBot 1.3.19／SDK 2.21.x。保持 Gateway 運行，在此專案目錄執行：

```bash
python3 scripts/install-maibot-plugin.py --maibot-dir /你的/MaiBot --gateway-key-file "$PWD/.state/gateway.key"
```

先在 Mai Chat 輸入 `/mm status`，設定插件啟用及測試流 allowlist，再用 `/mm image gpt 白色桌上的紅蘋果` 或 `/mm chat grok 你好`。Grok 影片走可選工具與 Host 檔案服務。完整步驟與限制見 [MaiBot 插件指南](docs/MAIBOT.md)。不修改核心；未連接正式 QQ，真實 Host 傳送仍待本機驗證。

## 測試及文件

```bash
python3 -m unittest discover -s tests -v
node tests/chatgpt.test.mjs
```

目前 Gateway Python 80 項、Node 3 項及獨立插件／安裝 19 項程式測試通過。使用者回報 Grok CLI 圖片與影片生成成功；GPT Plus 訂閱生圖也已由使用者回報成功，Gemini Ultra 仍待帳號端到端驗證。

- [Plus／Ultra 訂閱生圖](docs/SUBSCRIPTION-IMAGES.md)
- [Google Ultra / Antigravity 修正](docs/ANTIGRAVITY.md)
- [DSH 端點、認證及宿主邊界](docs/DSH-REVIEW.md)
- [CLI 媒體合約及限制](docs/MEDIA.md)
- [測試記錄](docs/TESTING.md)
- [MaiBot 插件安裝與使用](docs/MAIBOT.md)

歷史審查資料中的能力狀態與舊登入指引可能已失效，以本 README 及對應更新文件為準。`research/` 為開發環境本機研究快照，不隨倉庫發布；原始碼證據以文件中的固定 commit 連結查閱。
