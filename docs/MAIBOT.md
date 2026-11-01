# 後續 MaiBot 最小接入方案

本輪只建立 Gateway，未安裝或改動任何 MaiBot 實例。先使用獨立測試實例及本地測試訊息，不配置正式 QQ。

1. 若部署版本已有 OpenAI 相容 provider，設定 base URL `http://127.0.0.1:8790/v1`、獨立 Gateway key，模型填 `openai/...` 或 `xai/...`；確認客戶端關閉 streaming 且不傳未支援欄位。實際相容性待指定 MaiBot 版本測試。
2. 若現有 provider 會附加 tools、temperature 等欄位，新增小型插件的 `LLMProvider` adapter，將 `operation=response` 的純文字 message_list 轉成本 Gateway 的 messages，取回 choices[0].message.content，再回傳 `{"content":...}`。Manifest 的 llm_providers 與 `@LLMProvider` client_type 必須一致。其他 operation 明確拒絕。依目前官方文件使用 `maibot-plugin-sdk`，不要套用舊版 Action API。
3. 圖片使用獨立 Tool/Command，送 Gateway `/v1/images/generations`，驗證並解碼 b64，以 MaiBot 該版本支援的圖片傳送 API 回傳；不要把 `.state` 路徑或 key 放進工具參數、模型上下文或訊息。Gateway 不需要 DSH attachment service。
4. 插件僅持有 Gateway key，服務商憑證留在 Gateway；依序驗證本地文字、圖片、錯誤 401/403/429、timeout，再評估測試聊天平台。

若 MaiBot Runner 在容器內，127.0.0.1 並非宿主 loopback，需另行設計同網路命名空間或本機 IPC；本輪不開啟 0.0.0.0。

來源：https://docs.maibot.chat/plugin/llmprovider 。這是接入設計，不是已通過 MaiBot integration 的插件。
