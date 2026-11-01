# MaiBot Multimodal Gateway 插件

獨立 Host/Runner 插件，透過 `127.0.0.1` 呼叫既有 Gateway。目標 MaiBot 1.3.19–1.3.99、官方 SDK 2.21.x；不使用舊 Action API，不修改核心、不啟動登入、不接正式 QQ。

完整文件：[安裝、設定與驗證](https://github.com/AyakaNya/maibot-multimodal-gateway/blob/main/docs/MAIBOT.md)。

## 安裝

在 Gateway 專案目錄執行，將 MaiBot 路徑換成實際位置：

```bash
python3 scripts/install-maibot-plugin.py --maibot-dir /你的/MaiBot --gateway-key-file "$PWD/.state/gateway.key"
```

只會新增 `MaiBot/plugins/maibot_multimodal_gateway/`，key 只保存路徑，不複製任何憑證。更新插件加 `--update`，保留既有 `config.toml`。也可直接複製本目錄到 MaiBot 的 plugins 目錄。

MaiBot Runner 與 Gateway 必須同一台 Mac、同一使用者，且 Runner 可讀取 Gateway key（0600）。容器內的 loopback 不是宿主，這版不會改綁外網或自動開 tunnel。

先啟動 Gateway，再載入／重新載入插件。用 **Mai Chat 本機測試聊天**輸入 `/mm status`，將回報的流 ID 加入插件 `config.toml` 的 `access.allowed_stream_ids`，設定 `plugin.enabled=true`。安裝器已設定 key 路徑時不必重填；手動安裝請參考 `config.example.toml`。本插件不接受 QQ 平台呼叫。

## 明確命令

```text
/mm
/mm status
/mm chat grok 只用一句話介紹自己
/mm chat gpt 只用一句話介紹自己
/mm chat gemini 只用一句話介紹自己
/mm image grok 森林湖泊，水彩風格
/mm image gpt 白色桌上的紅蘋果
/mm image gemini 一隻在窗邊睡覺的貓
```

圖片透過 SDK `send.image` 回傳當前測試流。輸入的提示詞只送到 Gateway，不寫入插件 log。`gpt` 對應 `chatgpt/default`；文字與圖片的登入方式沿用 Gateway，各提供者的實際權限仍由其 runtime 決定。GPT／Grok 圖片已有使用者 Gateway 實測回報；Gemini 仍待真實帳號確認。

## LLM 工具與影片

設定 `features.tools_enabled=true` 後，Mai Chat 規劃模型可選 `gateway_image(provider,prompt)`。工具參數不提供 key、URL、檔案路徑或目的聊天，平台範圍為 `internal`，且生成前仍檢查流 allowlist。

影片使用 `gateway_video(prompt)`，**沒有 `/mm video` 命令**。因官方 SDK 的檔案傳送需要 Host 簽發「目前工具呼叫」作用域，不能在 Command 裡假造此權限。

影片需另設定 `features.video_enabled=true`，並由管理員在 MaiBot 啟用檔案服務與此插件的 `files.list`／`files.upload`／`files.send` 能力。工具會先檢查檔案服務，再生成 Grok 六秒影片、驗證 MP4／大小／SHA256，透過官方檔案傳輸回到當前聊天。未開檔案服務會先拒絕，不消耗影片額度。檔案服務回 `unknown` 時不自動重發或再次生成。

## 可選純文字 Provider

`client_type=ayakanya.multimodal_gateway` 已同時在 manifest 與裝飾器註冊。需另開 `features.llm_provider_enabled=true`。支援 `response`、純文字 `message_list`／Context Item schema 1；圖片輸入、工具呼叫、structured output、embedding／ASR 明確拒絕。不要用它替代需要 function calls 的 planner，也不要把不支援的內容默默轉成文字。

`model_identifier` 使用 `grok/default`、`chatgpt/default` 或 `gemini/default`。Provider 的 base_url／api_key 不會覆蓋插件本機設定；Gateway key 只讀本機檔案。Host 的該 API provider 設 `timeout=660`、`max_retry=0`，避免 Host 自動重試已消耗額度的生成。設定範例在主文件；插件不替你修改模型配置。

## 執行限制

- 共用一個 HTTP 請求槽；忙碌立即拒絕，同一流預設間隔五秒。
- 同步 HTTP 放在 worker thread，避免阻塞 Runner。呼叫方取消時仍持有槽，直到原 HTTP 結束；HTTP timeout 不表示提供者已取消生成。插件不自動重試。
- 僅允許 IPv4 loopback 原點，停用代理與 redirect。訂閱路由不切換 API key。
- 媒體須為唯一 base64 產物，MIME／magic／大小／bytes／SHA256 均通過才傳送。沒有讀取模型輸出路徑或 URL 的功能。
- 圖片與文字傳送會檢查 Host 回執。生成已完成但傳送失敗時回報未確認，不重新生成。
- 憑證、config.toml、產物不進 Git。此目錄 MIT 授權，不改變其他 runtime／SDK 的授權。

目前驗證以真實官方 SDK、模擬 Host 能力／提供者和本機 HTTP 為主。沒有連接正式 QQ；不宣稱已在使用者 MaiBot 實例完成傳送。
