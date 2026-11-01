# 原始碼審查與能力矩陣

審查日期：2026-10-30。這是靜態程式碼審查；沒有使用者帳號、套餐、服務商 API key 或正式核准 OAuth client，因此所有帳號 entitlement 均為「未驗證」。登入成功、JWT tier 或出現在模型清單不等於該端點可用。

固定來源：

- [DSH b802311](https://github.com/V1ki/dsh-plugin-subscriptions/tree/b8023110864494acefc6f5963c2a197d85dda20c)
- [oauth-proxies 9860754](https://github.com/BhanuTabeti/oauth-proxies/tree/98607548fdad59af38225fd36d61c6e2c78a88c6)

`research/` 保存所審查原始檔與檔案樹，並非完整 clone，也不作執行依賴。引用程式碼僅供研究，不直接併入 Gateway。

| 能力 | 來源中的實際端點／請求格式 | 認證及限制 | Gateway 第一輪 |
|---|---|---|---|
| Grok 文字 | DSH `src/providers/grok.ts`: POST `https://api.x.ai/v1/responses`，JSON `model,input,stream`；oauth-proxies 也轉送 `/v1/chat/completions` | OAuth Bearer；PKCE/OIDC；token exchange 或 inference 可能 403。個別模型只接受 Responses | `xai/模型` 官方 key；`grok-oauth/模型` 需自有核准 client；非串流 |
| GPT/Codex 文字 | 兩者 POST `https://chatgpt.com/backend-api/codex/responses`，JSON `model,input,instructions,store:false,stream:true`，上游 SSE | Bearer、`ChatGPT-Account-ID`、`originator:codex_cli_rs`；不是公開 OpenAI API 端點 | 訂閱路徑未啟用；`openai/模型` 使用官方 `https://api.openai.com/v1/responses` |
| GPT 圖片生成 | DSH `src/tools/image-generate.ts`: POST `https://chatgpt.com/backend-api/codex/images/generations`，JSON `model,prompt,size?,quality?` | Codex Bearer、account-id、originator；程式碼存在不能證明帳號或獨立應用有權使用 | 訂閱停用；官方 `https://api.openai.com/v1/images/generations` key 路由已實作 |
| GPT 圖片編輯 | DSH POST `https://chatgpt.com/backend-api/codex/images/edits`，前述 JSON 加 `images:[{image_url:dataURL}]` | 同上；輸入圖片從 DSH attachment store 讀取 | 未實作；可選官方 `/v1/images/edits`，需依官方格式另外實作，不直接套用 backend JSON |
| Grok 圖片生成 | DSH 與 oauth-proxies POST `https://api.x.ai/v1/images/generations`；DSH JSON `model,prompt,response_format:b64_json,aspect_ratio?,quality?` | Grok OAuth Bearer；逐能力 entitlement 未驗證。官方文件展示 API key | 官方 key 已實作，訂閱圖片明確回 403；size 轉 aspect_ratio，不送 quality |
| Grok 圖片編輯 | DSH POST `https://api.x.ai/v1/images/edits`；JSON 加單圖 `image:{type:image_url,url}` 或多圖 `images:[{type:image_url,url}]` | Grok OAuth Bearer；附件輸入依賴 DSH 宿主；權限未驗證 | 未實作；官方 key 可作後續替代 |
| Grok 影片 | DSH `src/tools/video-generate.ts`: POST `https://api.x.ai/v1/videos/generations`，JSON `model,prompt,duration?,aspect_ratio?,resolution?,image:{url}?`；GET `/v1/videos/{request_id}` 輪詢，完成後下載 signed URL | Grok OAuth Bearer；signed URL 下載不帶 token。oauth-proxies 未路由影片 | 未實作；官方 key 可選，不能由圖片成功推論影片權限 |
| Grok 語音 | 本輪所查 provider/tool 註冊未見語音實作；官方文件為 `wss://api.x.ai/v1/realtime?model=grok-voice-latest`，`session.update` 及音訊事件 | 官方文件 API-key Bearer；無證據支持訂閱 OAuth | 未實作／訂閱權限未知 |
| GPT 語音／影片 | 所查兩者 Codex transport 及 DSH tool 註冊未提供可核實的專用實作 | 不能由 Codex 文字 token 推論音訊／影片存取權 | 未實作；官方 Audio/Realtime/Video API 待獨立審查 |

## OAuth 實作與正式允許範圍

DSH Grok 與 oauth-proxies Grok 使用相同 CLI public client ID `b1a00492-073a-47ea-816f-4c329264a828`；OIDC discovery 在 `https://auth.x.ai/.well-known/openid-configuration`，從中取得 authorization/token endpoint。scope 為 `openid profile email offline_access grok-cli:access api:access`。DSH loopback 為 `127.0.0.1:56121/callback`。授權碼換 token 為 form-urlencoded `grant_type=authorization_code,client_id,code,redirect_uri,code_verifier,code_challenge,code_challenge_method=S256`；刷新為 `grant_type=refresh_token,client_id,refresh_token`。

Codex 使用 `app_EMoamEEZ73f0CkXaXp7hrann`，`https://auth.openai.com/oauth/authorize`、`https://auth.openai.com/oauth/token`，scope 包括 `openid profile email offline_access api.connectors.read api.connectors.invoke`。oauth-proxies loopback 為 port 1455/1457、`/auth/callback`。認證是 PKCE，不代表服務商授權所有第三方應用重用 CLI 身分。oauth-proxies 還自行送高版本號取得模型清單；本專案不沿用該做法。

Gateway 不內建這些 CLI client ID、不讀取其他應用的 token、不抓 cookie、不重試繞過 403、不切帳號池、不自動轉付費 key。Grok OAuth 為實驗性接點：必須取得服務商允許此用途的 client、redirect URI 和 scopes 才可配置。此環境沒有這些資料，因此尚未驗證實際 consent、刷新及推論；不能稱為可用的訂閱整合。GPT 訂閱文字保留待辦，第一輪 GPT 走官方 key。

## DSH 插件與宿主邊界

插件自行實作：OAuth、token 管理、provider adapters、請求轉換、圖片生成/編輯請求、影片提交與輪詢、下載與寫檔、工具定義、專屬 toolview。

宿主提供：`ctx.llm.registerAdapter` 的模型路由、`ctx.tools` 的註冊與執行、agent/session context、`@deepseek-ai/dsh-attachment` 的持久附件保存及引用、前端渲染基礎、RPC/服務注入。`src/index.ts` 約 1370 行也明確說明 `web_search` 是宿主工具，插件只註冊其 provider seam。圖片端點不是宿主代為提供，但完整 inline 圖片流程需要宿主附件服務。不能把畫面上的附件、音訊或影片呈現當成訂閱端點證據。

## 官方參考

- [xAI 圖片生成](https://docs.x.ai/developers/model-capabilities/images/generation)：API key、b64_json、目前文件模型 `grok-imagine-image-2.0`；模型需以帳號可用清單為準。
- [xAI 影片](https://docs.x.ai/developers/model-capabilities/video/generation)
- [xAI 語音](https://docs.x.ai/developers/model-capabilities/audio/voice)
- [OpenAI 圖片](https://developers.openai.com/api/docs/guides/image-generation)：官方 API 路徑與可能的組織驗證要求。
- [MaiBot 插件](https://docs.maibot.chat/plugin/) 與 [LLMProvider](https://docs.maibot.chat/plugin/llmprovider)
