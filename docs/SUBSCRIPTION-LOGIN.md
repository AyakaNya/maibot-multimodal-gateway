# 訂閱登入方向更新（2026-11-01）

使用者要求改以 ChatGPT、Grok、Gemini 訂閱登入為主要路徑，API key 僅保留選項。現有 Gateway 尚未完成三家訂閱接入；不要把可登入官方工具當成已能由 Gateway 推論。

## 最新官方證據

- OpenAI：https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt 。官方提供本機個人／開源專案的 Sign in with ChatGPT，符合資格的 Plus/Pro 可授權 plan usage。必須分辨 identity 與額度使用權限；只有成功授予所需 scope 才能推論。優先研究官方 SDK 與動態 client registration，不需要直接沿用 Codex CLI client ID。這修正了 AUDIT.md 中只考慮自有預先核准 client 或 API key 的不完整結論。圖片及其他模態須另查模型與授權範圍。
- Grok：https://docs.x.ai/build/cli/reference 。官方 Grok Build 提供 `grok login`，以及 `grok models`。正式 CLI 登入可作本機帳號驗證起點，但 CLI 橋接、服務商允許範圍及各模態 entitlement 仍需獨立驗證；不抽取 CLI token 轉成任意 API 存取。
- Gemini：https://geminicli.com/docs/get-started/authentication/ 。本機執行 `gemini` 後選 Sign in with Google；Google AI Pro/Ultra 使用綁定方案的 Google 帳號。CLI 提供的模型／額度不等於 Gemini 網頁的全部功能，也不代表 Imagen、Veo 或語音 API 權限。CLI 的非互動呼叫與帳號登入憑證可用性須依官方版本確認。

## 尚待完成

1. 根據本機 OS 與實際訂閱方案選擇登入／安全儲存方案。
2. 審查並接入 OpenAI 官方登入 SDK，對 granted permissions 做檢查。
3. 審查 Grok/Gemini 正式 CLI 的自動化介面，限制工具權限與檔案存取，避免聊天請求變成可執行本機命令的 coding agent。
4. 各做一筆真實訂閱文字測試；再逐項驗證圖片，失敗保留 403，不自動轉 API 計費。

既有 5 項自動測試僅涵蓋先前 API 路徑與模擬上游，沒有驗證本文件中的三家訂閱整合。
