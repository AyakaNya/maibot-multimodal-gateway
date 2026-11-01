# MaiBot 插件接入

已提供獨立插件 `maibot_plugin/maibot_multimodal_gateway`。支援 **MaiBot 1.3.18–1.3.99、官方 SDK 2.20.x–2.21.x**，已核對 1.3.18／1.3.19 Host 原始碼，並在 SDK 2.20.0／2.21.0 各通過插件測試。未啟動完整 Host，不宣稱使用者實例載入已成功。無核心修改、無正式 QQ 連接。

## macOS 安裝

MaiBot Runner 與 Gateway 要在同一台 Mac、同一使用者及同一網路命名空間；容器中的 `127.0.0.1` 不是宿主。先按 [macOS 指南](MACOS.md) 完成 Gateway 安裝與所需服務的官方登入，沿用既有憑證。

在 Gateway 專案目錄：

```bash
git pull --ff-only
python3 -m gateway.app serve
```

另開終端，回到同一專案目錄，把 `/你的/MaiBot` 換成實際 MaiBot 根目錄：

```bash
python3 scripts/install-maibot-plugin.py \
  --maibot-dir /你的/MaiBot \
  --gateway-key-file "$PWD/.state/gateway.key"
```

安裝器只寫入 `MaiBot/plugins/maibot_multimodal_gateway/`。設定只記錄 Gateway key 的絕對路徑，不複製 key 或訂閱憑證；key 必須由同一使用者持有、權限 0600。不要把 key 貼到聊天或模型配置。安裝後插件預設關閉。

依 MaiBot 的插件管理流程載入／重新載入插件。先用 **Mai Chat 本機測試聊天**輸入 `/mm status`，取得目前測試流 ID。編輯插件目錄的 `config.toml`，保留其他設定，只調整：

```toml
[plugin]
enabled = true
config_version = "0.1.0"

[access]
allowed_stream_ids = ["貼上 /mm status 回報的測試流 ID"]
cooldown_seconds = 5.0
```

重新載入插件設定，再在同一 Mai Chat 測試流輸入：

```text
/mm chat gpt 用一句話介紹自己
/mm image gpt 白色桌上的紅蘋果
/mm image grok 森林湖泊，水彩風格
/mm image gemini 一隻在窗邊睡覺的貓
```

`gpt` 使用 ChatGPT 訂閱路由；`grok`、`gemini` 使用對應官方 CLI。圖片驗證後由官方 SDK `send.image` 回傳。命令不要求修改 MaiBot 的主聊天模型。若目前版本未暴露 Mai Chat 的 Command 呼叫入口，須先在測試 Host 確認入口，不能將此情況當成生成失敗而重試。

更新插件使用同一安裝命令加 `--update`，既有 `config.toml` 原樣保留。卸載先停用／卸載插件，再刪除該插件目錄，Gateway 與其登入資料不受影響。

### 沒有 bot.py：獨立實例／安裝版

新版 MaiBot 可將程式與實例資料分開。實例目錄只有 `config`、`data`、`plugins` 等資料夾時，不需要自行建立 `bot.py`，也不要將插件改裝進虛擬環境或內層程式目錄。以啟動命令 `maibot run --directory ...` 的 directory 為準，先從 MaiBot 啟動日誌或管理介面確認**實際 MaiBot 版本**（不是啟動器版本）。

例如實例在 `~/Documents/BSX-V3`，且已確認 MaiBot 為 1.3.18，在 Gateway 專案目錄執行：

```bash
python3 scripts/install-maibot-plugin.py \
  --instance-dir "$HOME/Documents/BSX-V3" \
  --host-version 1.3.18 \
  --gateway-key-file "$PWD/.state/gateway.key"
```

`1.3.18` 必須換成實際版本；不支援的版本會拒絕安裝，Host 仍會在載入時校驗 SDK／版本範圍。安裝器不執行內層 `my-maibot`，只新增指定實例的 `plugins/maibot_multimodal_gateway`，不修改既有核心、config／data 或其他插件。更新加 `--update`。此模式不會在你的 Mac 自動執行。

### 啟用出現「沒有對應的執行時」

插件 0.1.0 曾將最低 Host 版本設為 1.3.19。使用者實際 MaiBot 1.3.18／SDK 2.20.0 在啟用時被 Host 版本校驗排除；停用時略過執行時版本校驗，因此仍可顯示插件並切換成 inactive。已用官方 1.3.18 校驗器重現舊 manifest 被拒，0.1.1 改為支援 1.3.18／SDK 2.20.0，並驗證新版 manifest 通過。

在 Gateway 專案目錄更新，將版本／實例路徑換成實際值：

```bash
git pull --ff-only
python3 scripts/install-maibot-plugin.py \
  --instance-dir "$HOME/Documents/BSX-V3" \
  --host-version 1.3.18 \
  --gateway-key-file "$PWD/.state/gateway.key" \
  --update
```

會更新插件程式與 manifest，保留既有 `config.toml`。完整停止／重新啟動 MaiBot，再啟用插件；不必升級核心或 SDK。若仍失敗，提供新一輪啟動中該插件的第一個載入錯誤，不要重複安裝或改用 API key。

## 功能與實測界線

| 功能 | 插件入口 | 狀態 |
| --- | --- | --- |
| Grok／GPT／Gemini 文字 | `/mm chat 提供者 提示詞` | 已通過官方 SDK＋模擬提供者測試；帳號權限由 Gateway runtime 決定 |
| Grok／GPT 訂閱生圖 | `/mm image grok或gpt 提示詞` | Gateway 已有使用者真實成功回報；插件傳送待 Mac 驗證 |
| Gemini Ultra 訂閱生圖 | `/mm image gemini 提示詞` | 路由已接上；先前 CLI／設定阻擋，尚未取得真實成功回報 |
| 模型選用生圖工具 | `gateway_image(provider,prompt)` | 須開 `features.tools_enabled`；限 allowlist 中的 internal 測試流 |
| Grok 六秒影片 | `gateway_video(prompt)` | 須另開 `features.video_enabled` 及 Host 檔案服務；Gateway 已有使用者成功回報，插件真實傳送待驗證 |
| 模型 Provider | `ayakanya.multimodal_gateway` | 可選、預設關閉；Grok 可另開工具橋接與圖片理解，其他路由仍為文字 |
| 圖片編輯、語音、GPT／Gemini 影片 | 無 | 本插件未實作，不假設訂閱有權限 |

影片只有 Tool 入口，沒有 `/mm video`。官方檔案服務依真實工具呼叫簽發作用域，不能從 Command 假造。管理員需允許 `files.list`、`files.upload`、`files.send`；先做檔案服務檢查，再消耗影片額度。服務回傳送達狀態 `unknown` 時不自動重發或再生成。

## 模型 Provider：文字與 Grok 多模態

明確命令足以使用插件。需要將模型加入 MaiBot 任務時，開 `features.llm_provider_enabled=true`，並在 MaiBot 模型設定加入一個 API provider，例如：

```toml
[[api_providers]]
name = "local-subscription-gateway"
base_url = "http://127.0.0.1:8790/v1"
api_key = ""
auth_type = "none"
client_type = "ayakanya.multimodal_gateway"
timeout = 660
max_retry = 0

[[models]]
name = "gateway-gpt-text"
model_identifier = "chatgpt/default"
api_provider = "local-subscription-gateway"
model_type = "llm"
force_stream_mode = false
send_temperature = false
```

這是手動合併範例，不要覆蓋原有模型設定。Provider 的 URL／key 以插件 `config.toml` 為準，並不採用模型配置中的 key。模型也可用 `grok/default` 或 `gemini/default`。只在獨立本機測試模型任務使用；Provider 請求沒有可靠的平台上下文，**命令／工具的 internal 流限制不適用於 Provider**，請勿將它指定給正式聊天任務。

文字支援新版 `context_items` schema 1 與舊 `message_list`。插件 0.2.0 可另開 Grok JSON 工具呼叫橋接與圖片輸入，見 [Grok 多模態設定](GROK-MULTIMODAL.md)；原有 GPT／Gemini 路由仍為純文字，不支援其 planner 工具呼叫。structured output、embedding／ASR 明確拒絕。不轉送 temperature、max_tokens 或任意 extra_params，也不宣稱能控制原生訂閱 CLI 的這些參數。

## 安全、驗證與限制

插件僅持有 Gateway key 路徑。僅允許 `http://127.0.0.1:PORT`，不使用代理、重新導向或任意產物 URL／路徑。單一 HTTP 請求槽、流冷卻、不自動重試；呼叫方取消時仍等待背景 HTTP 結束才釋放槽。超時不代表提供者取消生成。

圖片與影片須為唯一 base64 產物，且 MIME、檔頭、大小、bytes、SHA256 一致。圖片／文字檢查 Host 回執；影片以官方檔案服務上傳及傳送。媒體已生成但未確認送達時，錯誤會提醒不要重新生成。訂閱失敗不轉用付費 API key；官方 API 替代仍由獨立 Gateway 流程明確選用。

測試命令：

```bash
python3 -m venv /tmp/maibot-plugin-test
/tmp/maibot-plugin-test/bin/pip install 'maibot-plugin-sdk==2.21.0' 'jsonschema>=4,<5'
/tmp/maibot-plugin-test/bin/python -m unittest discover -s maibot_plugin/tests -v
```

26 項插件／安裝測試在 SDK 2.20.0／2.21.0 各通過，使用真實官方 SDK、本機 Gateway HTTP、模擬提供者／Host RPC 與本機檔案上傳服務。不是完整 MaiBot Host 整合測試，未在使用者 Mac／正式 QQ 發送，也未消耗訂閱額度。完整記錄見 [TESTING.md](TESTING.md)。

來源：[官方插件文件](https://docs.maibot.chat/plugin/)、[MaiBot 核對版本](https://github.com/Mai-with-u/MaiBot/tree/c6429547af711555e3d4d1b8d04b413572cb616c)、[SDK 核對版本](https://github.com/Mai-with-u/maibot-plugin-sdk/tree/aa9ab7b347f9d011a3e0b00addee46de8f16bf9e)。

1.3.18 核對來源：[官方發佈 commit](https://github.com/Mai-with-u/MaiBot/commit/2a9af62cec37035d29237acbe2cf3adceb700b27)。SDK 2.20.0 的 components、LLMProvider、send、files 介面與 2.21.0 相同；本插件不使用 2.21.0 新增的桌寵按鈕功能。
