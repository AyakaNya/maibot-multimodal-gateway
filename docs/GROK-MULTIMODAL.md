# Grok 訂閱：MaiBot 工具呼叫與圖片理解

插件 0.2.0 在既有 `grok/default` 路由新增工具決策橋接及圖片輸入。沿用官方 Grok Build 登入，不抽出 token、不更換 client、不轉付費 API。相容 MaiBot 1.3.18／SDK 2.20.0；SDK 2.21.0 也有回歸測試。

## 支援界線

| 能力 | 實作 | 驗證狀態 |
| --- | --- | --- |
| 文字 | 既有官方 CLI 訂閱路由 | 保留 |
| MaiBot 工具呼叫 | CLI `--json-schema` → 驗證結構化決策 → Host 執行 → 下一次請求帶回結果 | 模擬 CLI 真實子程序、官方 SDK＋本機 HTTP 往返通過；真實帳號／Host 工具執行待測 |
| 圖片理解 | MaiBot ContextImagePart → base64 ACP image → CLI 私有 `.json` prompt-file | 模擬 CLI＋官方 SDK 傳輸通過，真實帳號待測 |
| 圖片／影片生成 | 既有 `/mm image grok`、可選媒體 Tool | Gateway 已有使用者成功回報，與圖片理解是不同路徑 |
| SuperGrok 語音檔輸入／轉寫、語音輸出 | 未找到本 Gateway 可用的正式 CLI 檔案介面 | 明確拒絕，不啟用 |

工具呼叫是**JSON Schema／提示詞橋接**，不是原生 xAI API function calling。CLI 本身的 shell、檔案、web、MCP、子代理工具持續關閉；只有本次 MaiBot 提供的函數才可回傳為 FunctionCallItem。每次最多一個，後續結果以配對 call_id 回送。參數須通過該函數的 JSON Schema，拒絕遠端 schema 引用。工具實際權限與執行仍由 MaiBot 管理，不會因選了此模型就取得額外權限。

這種橋接比原生工具協定更依賴模型是否正確遵循格式。只有 CLI 的 `structuredOutput` 被接受；不從一般文字、Markdown code fence 或思考內容擷取工具指令。格式錯誤、未知工具、參數錯誤或回合未完成時停止，不自動重試／修補／換 API。

## 更新與開啟

保持原有版本即可，不用升級 MaiBot 核心或 SDK。在 Gateway 專案目錄：

```bash
git pull --ff-only
python3 scripts/install-maibot-plugin.py \
  --instance-dir "$HOME/Documents/BSX-V3" \
  --host-version 1.3.18 \
  --gateway-key-file "$PWD/.state/gateway.key" \
  --update
```

更新器保留 `config.toml`，不會替既有安裝自動開啟新功能。編輯實例的 `plugins/maibot_multimodal_gateway/config.toml`，在**既有** `[features]` 區段新增／調整，不要重複建立同名區段：

```toml
llm_provider_enabled = true
provider_tool_calls_enabled = true
provider_vision_enabled = true
```

前兩個新旗標與 `tools_enabled` 不同：`provider_tool_calls_enabled` 允許模型選擇 Host 提供的工具；`tools_enabled` 則允許本插件自己的生圖／影片 Tool 消耗訂閱額度。若希望模型也能選用 `gateway_image`，另開 `tools_enabled=true` 並保留測試流 allowlist；影片還需 `video_enabled` 與 Host 檔案服務。

重新啟動 Gateway 與 MaiBot，再啟用插件。模型提供商繼續使用：

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
name = "gateway-grok"
model_identifier = "grok/default"
api_provider = "local-subscription-gateway"
model_type = "llm"
visual = true
force_stream_mode = false
send_temperature = false
```

手動合併設定，保留現有其他提供商、模型及任務。WebUI 強制 API Key 必填時可填 `unused-local-plugin`；真正 key 仍來自插件的本機 Gateway key 檔。先在獨立本機測試任務選 `gateway-grok`；圖片須由 Host 以圖片內容提交，單純在文字中附 URL 不會下載。Provider 請求缺少可靠的平台上下文，命令／媒體 Tool 的 internal 流 allowlist 不適用於 Provider；本輪沒有配置或測試正式 QQ。

## 不接 MaiBot 的真實訂閱 PoC

以下命令會消耗 Grok 訂閱額度。先保持 Gateway 運行，再於同一專案目錄執行：

```bash
# 圖片理解；檔案必須是自己選定的本機 PNG/JPEG/WebP/GIF。
python3 scripts/chat-poc.py --image /你的/測試圖片.png --prompt '描述這張圖片的內容'

# 工具往返：僅執行固定的本機 echo，不執行 shell、網路或聊天發送。
python3 scripts/chat-poc.py --tool-demo --prompt '先呼叫 gateway_echo，text 填入你好；拿到結果後再回答'
```

工具測試最多兩次模型請求、一次 echo。若模型直接回答而未選工具，會明確提示未呼叫，不能把它當成工具測試成功。請回報文字輸出或固定錯誤碼，不分享登入資料。真正 MaiBot 工具執行仍需在 Host 測試，PoC 不能代替該項驗證。

## 限制與診斷

- 每張圖片最多 4 MiB，最多四張；整體 HTTP JSON 最多 8 MiB，文字與工具描述合計最多 256 KiB。只接受 base64 data URL，拒絕任意 HTTP URL、file URL 或模型提供的路徑。
- `tool_choice` 支援 auto／none；required 或指定函數強制選擇明確拒絕。工具參數只支援 JSON object；不支援 stream、structured response_format、embedding 或 ASR。
- 使用 MaiBot ContextItem schema 1 的文字、使用者圖片、FunctionCallItem、FunctionCallOutputItem；其他內容明確拒絕。工具結果不會被默默略過。Grok CLI 的角色歷史仍是 JSON conversation 投影，不宣稱等同原生 Chat Completions role 語義。
- 保留單請求槽，Provider 的工具往返不受測試聊天命令的五秒冷卻限制，避免快速工具結果被攔住；不自動重試。CLI 自己可能保存 session，遵循其本機儲存策略；Gateway 暫存 prompt 會刪除，不在 HTTP 或 log 輸出憑證。
- `grok_update_cli_for_multimodal_json_bridge`：實際 CLI help 沒有列出必要選項，請依官方方式更新 CLI，不能只修改版本字串。
- `grok_invalid_or_unfinished_tool_bridge_output_no_retry`：CLI 沒有完成、沒有可信 structuredOutput 或工具決策不合法；不要自動重複有副作用的工具。
- `invalid_gateway_tool_response`：決策未通過函數名稱／參數 Schema 校驗，Host 未收到可執行工具呼叫。

## 語音：僅訂閱，不使用替代方案

依使用者要求，不加 Whisper、本機 TTS 或 API-key fallback。Grok Build 原始碼有麥克風擷取與互動語音轉寫，不等於有可供 Gateway 傳入音訊檔的 headless 功能。獨立 `voice-probe` 又要求 XAI_API_KEY，不能當成 SuperGrok 訂閱入口。ACP 的通用 AudioContent 型別存在，也不足以證明 shell 會將音訊送給模型；本版不送出可能被忽略的音訊區塊。

MaiBot `audio_transcription` 會在 HTTP 前回 `supergrok_subscription_audio_file_interface_unavailable`；Gateway 的 `/v1/audio/transcriptions`、`/v1/audio/speech` 繼續明確拒絕。不要把 `gateway-grok` 指定為 ASR／TTS 模型。本版沒有宣稱完整訂閱語音已完成。

原始碼證據（固定 commit `2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8`）：[私有 JSON prompt 支援](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-pager/src/headless/cli.rs)、[結構化結果欄位](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-pager/src/headless/reducer/mod.rs)、[圖片輸入處理](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-shell/src/session/acp_session_impl/prompt_build.rs)、[語音 probe 的 API-key 要求](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-voice/src/bin/voice_probe.rs)。
