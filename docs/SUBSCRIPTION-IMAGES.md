# ChatGPT Plus／Google AI Ultra 訂閱生圖

本版新增兩條官方 runtime 生圖路由。這是已實作、待使用者 Mac 帳號端到端驗證的狀態，不能把模擬圖片 fixture 當作真實生成成功。

| Gateway model | 執行方式 | 登入 | 實測狀態 |
|---|---|---|---|
| `chatgpt/default` | 官方 Codex app-server 原生 `image_gen.imagegen` | 本專案獨立 `codex login`，ChatGPT Plus 帳號 | 使用者已回報 Gateway 生圖成功 |
| `gemini/default` | 官方 Antigravity CLI 原生 `generate_image` | 官方 agy 個人 Google 帳號／Ultra | 參數與模擬生成通過，帳號生成待驗證 |
| `grok/default` | 官方 Grok CLI 原生媒體工具 | 官方 Grok 登入 | 使用者已回報圖片與影片成功 |

這些使用官方 runtime 的訂閱授權；不設定 API key、不轉送登入 token、不使用 DSH 的 public client ID。各 runtime 的額度、credits、模型與服務端權限由提供者判定，不能將它們視為網頁版生圖額度的同一個池，也不保證特定圖片模型。Google 本次設定明確關閉 `useG1Credits` 額外額度續用；Gateway 不購買 credits。

## 更新與登入

先 Ctrl+C 停止舊 Gateway，再在原專案目錄執行：

```bash
git pull --ff-only
npm install -g @openai/codex
```

Antigravity 尚未安裝時，依 [官方安裝文件](https://antigravity.google/docs/getting-started?tab=cli)安裝；已安裝時可用 `agy update` 更新。新版必須在 `agy --help` 中提供 `--settings`（僅本次 session 生效）。不支援的舊 CLI 會在生圖前拒絕，不會退回全域放行或 API。

```bash
python3 -m gateway.app login-images --provider chatgpt
python3 -m gateway.app login-images --provider gemini
```

ChatGPT 選擇 ChatGPT 帳號登入，使用 Plus 帳號。登入由官方 Codex CLI 完成，憑證使用 native auto 儲存方式（可用時使用系統 keyring，否則保存在專案受保護目錄）；Gateway 不解析憑證。獨立 profile 是 `.state/codex-images/`，不是你全域 `~/.codex`，也不是先前文字 SIWC 登入。**之前文字登入成功，仍需完成這次 Codex 圖片登入。**

Google 使用已綁定 Ultra 的個人帳號；之前已登入 agy 可沿用。生圖不要求更改全域 Tool Permission，使用新版 agy 的本次設定；若另使用文字路由，該路由仍要求全域 strict。登入完成後退出 `/quit`。不要使用舊 Gemini Code Assist 登入。Gateway 會拒絕共享 hooks／MCP／plugins、customModelsConfig 與 API／Cloud project 設定，避免執行未審查擴充或使用其他計費來源。

然後啟動新版：

```bash
python3 -m gateway.app serve
```

另開終端，在同一專案目錄生圖：

```bash
python3 scripts/media-poc.py --provider chatgpt --kind image --prompt '白色桌上的紅蘋果，柔和自然光'
python3 scripts/media-poc.py --provider gemini --kind image --prompt '白色桌上的紅蘋果，柔和自然光'
```

每次指令各執行一次請求，不需要額外安裝 Python SDK。成功後輸出產物資訊，圖片分別寫入 `artifacts/chatgpt-poc.*`、`artifacts/gemini-poc.*`。如果失敗，先分享以下去敏診斷，不用再次生成：

```bash
cat .state/subscription-image-diagnostic.json
```

不要分享 auth.json、Keychain 內容或原始 runtime 日誌。

## HTTP 呼叫與限制

端點為 `POST http://127.0.0.1:8790/v1/images/generations`，使用獨立 Gateway bearer key。請求例如：

```json
{"model":"chatgpt/default","prompt":"一隻在窗邊睡覺的貓","n":1,"size":"auto"}
```

Gemini 將 model 改成 `gemini/default`。目前只接受 `n:1`、`size:auto`（可省略），圖生圖／編輯另未接入。輸出沿用 `data[].b64_json,media_type,bytes,sha256`。不要把圖片模型 ID 放在 model 欄位；`default` 表示由官方 runtime 選擇可用模型，Gateway 沒有宣稱能切換特定圖片模型。

共用單一並發；忙碌回 429。單次 runtime 最長 600 秒；GPT 提供者由原生 `account/read` 確認為 ChatGPT 登入才開啟生成，API-key 帳號拒絕。失敗不啟動第二次生成、不換帳號或 API key。Agent 工具可能消耗多輪模型用量；提示要求只呼叫一次生圖，並非可繞過官方 quota 的固定成本 API。

Codex 使用 app-server JSONL 協定 initialize → account/read → thread/start → turn/start，只收原生 `imageGeneration` 完成事件，成功即停止本次 runtime。關閉 shell、web、plugins/hooks、host skills discovery、多代理，thread 使用 read-only sandbox。它的原生圖片工具可以保存自己的圖片產物。只接受圖片事件中的 inline 圖片或本次 workspace／thread 的圖片路徑，不接受 assistant 文字中的任意路徑與 URL。

Antigravity 使用隨機名稱的 workspace 專用主代理，只提供 `generate_image`，不是多代理委派。本次 `--settings` 將權限設為 request-review，拒絕 command/MCP/web，關閉額外 G1 credits，不寫入全域 settings。只收原生 tool DONE 與最終 SUCCESS，從本次 workspace 或 conversation UUID 對應的 brain 目錄取得唯一圖片。未知協定或找不到唯一圖片時明確失敗，不把模型文字當成圖片。CLI 權限不是本專案提供的完整 OS 隔離，只供受信任本機使用者。

## 原始碼與授權證據

- [Codex 官方登入說明](https://learn.chatgpt.com/docs/auth?surface=cli)及 [ChatGPT 計畫與 Codex](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)：支援 ChatGPT 訂閱登入，額度與 ChatGPT 圖片用量需分開判斷。
- [Codex 原生圖片工具](https://github.com/openai/codex/blob/67f0994b532b8740f14b5b738af7b7b2a915b1d6/codex-rs/ext/image-generation/src/tool.rs)：native `image_gen.imagegen`，支援圖片完成事件與本機產物。
- [Codex 工具提供條件](https://github.com/openai/codex/blob/67f0994b532b8740f14b5b738af7b7b2a915b1d6/codex-rs/core/src/tools/spec_plan.rs)：本機 feature 開啟不等於有服務端權限，仍檢查 provider／登入與模型條件。本實作不修改這些檢查。
- DSH 已核對的 `chatgpt.com/backend-api/codex/images/generations`／`edits` 及 `gpt-image-2` 是它直接傳 HTTP 的路徑，見 [原審查](DSH-REVIEW.md)。本版改用官方 app-server 完成登入、HTTP 呼叫與 refresh，不移植 DSH 的 token 或 headers。
- [Antigravity CLI 官方原始倉庫／發行記錄](https://github.com/google-antigravity/antigravity-cli)、[主代理自訂工具](https://antigravity.google/docs/subagents?tab=cli)、[headless tool_info 協定](https://antigravity.google/docs/cli/headless)、[原生圖片工具清單](https://antigravity.google/docs/sdk/tools)。`generate_image` 的內部 HTTP 端點與完整 payload 尚未獨立審查，本 Gateway 不猜測或直接呼叫其未公開 API。
- Antigravity Python SDK 0.1.23 的 LocalAgentConfig 預設組合 Gemini API endpoint；不能僅因 SDK 有 GENERATE_IMAGE，就假設會用個人 Ultra 登入。本版不使用該 SDK，採正式 agy CLI 登入。

## 驗證範圍

Python 60/60、Node 3/3 程式測試通過，涵蓋 native 事件、帳號類型 guard、產物範圍、敏感錯誤去敏、session 設定不持久化、舊 agy 拒絕、並發釋放與真實 stdio timeout cleanup。

額外使用 Codex CLI 0.163.0，透過空白獨立 profile 完成 initialize／account/read，確認未登入；匯出 native schema 核對 imageGeneration／result／savedPath。官方 agy 1.4.12 Linux 發行檔經 SHA512 校驗，確認 --settings/--agent/help 參數；未登入下的 agents 列表未提供可驗證的 agent 資訊。因此這不是 macOS、keyring 或兩家帳號生成的實測證明，首次生圖可能需要依去敏診斷調整 CLI 差異或確認帳號功能開放。


## macOS 工具完成後的 unsafe_media_path 修正

使用者回報 Codex 原生圖片工具 completed，但 Gateway 回 unsafe_media_path。已在本地重現：可信暫存目錄的祖先是 symlink（如 macOS /var → /private/var），舊程式只將 root resolve，卻沿原始 path 向上檢查，誤將系統目錄別名當成產物 symlink。這是 Gateway 可重現的路徑相容錯誤，不代表圖片授權失敗；仍需 Mac 更新後確認實際取圖。

新版將 Codex cwd 正規化，接受同一可信根目錄的 alias／canonical 表示；開啟產物時以目錄 fd 逐層 no-follow，仍拒絕產物內的檔案或目錄 symlink、越界和 ..。不會放行任意 savedPath 或 assistant 文字中的路徑。

去敏診斷新增 artifact_collected；工具完成但收集失敗時為 false，另附固定 artifact_error。tool_completed:true 本身不代表 Gateway 已回傳有效圖片。

更新後停止並重啟 Gateway，再執行一次 ChatGPT 圖片 PoC，無需重新登入：

```bash
git pull --ff-only
python3 -m gateway.app serve
```

另開終端：

```bash
python3 scripts/media-poc.py --provider chatgpt --kind image --prompt '白色桌上的紅蘋果'
```

60 項 Python 測試通過，包括兩種根目錄／檔案路徑表示的互通、Codex inline／savedPath、目錄 fd 防止替換連結逸出、內部 symlink／越界拒絕與取圖診斷。本輪未使用真實訂閱重新生成。


## Gemini 生圖的全域 strict 誤擋修正

使用者已回報 GPT 圖片成功；Gemini 在生成前回 503 antigravity_set_toolPermission_strict_in_config。原因是生圖已提供本次 --settings 覆蓋，卻仍呼叫文字路由的 strict 前置檢查。

新版生圖不要求全域 strict；settings.json 不存在或未設定 toolPermission 時也可使用本次受限設定，不會建立或改寫全域檔。損毀／無法讀取／格式不符的設定仍明確拒絕。文字路由尚未使用本次覆蓋，保留原 strict 要求。

原有 permissions.allow／ask／deny 全數保留，再附加 command／MCP／web deny。覆蓋設定放在本次 0700 工作目錄下的 0600 暫存檔，透過 --settings 檔案路徑傳入，不將私人規則寫入程序參數。舊 CLI 不支援 --settings 時仍在生成前拒絕；個人帳號、API／Cloud 設定與共享擴充檢查不變。

停止舊 Gateway，git pull --ff-only，再用 python3 -m gateway.app serve 重啟；另開終端執行原 Gemini 圖片 PoC 即可。64 項 Python 測試通過；這確認 Gateway 設定誤擋已修正，不代表 Ultra 上游生成已實測成功。


## Gemini 的 shared_extensions_require_review

這是 Gateway 的本機前置檢查，不是 Google 權限或額度錯誤；在此階段沒有執行生圖。舊版只檢查 JSON 外層是否非空、plugins 目錄有無任何項目，會誤擋空 hooks 事件清單、已停用 hooks／MCP 及 .DS_Store 等檔案。

新版依 [官方 hooks 格式](https://antigravity.google/docs/hooks?tab=cli)辨識 named hook groups 的 enabled:false，以及 [官方 MCP 格式](https://antigravity.google/docs/mcp?tab=cli)的 disabled:true；也接受空的相容 hooks envelope。停用項保留設定，不會刪除或改寫。plugins 中的 .DS_Store、README／LICENSE、.gitignore 與空目錄不算已啟用擴充。非空 plugin 目錄仍列為待審候選，並不宣稱已判定它是 enabled；停用 plugin 但保留目錄也可能仍列為候選。

更新後先直接執行離線檢查，不需重啟 Gateway、登入或再生成：

```bash
git pull --ff-only
python3 scripts/antigravity-diagnostic.py
```

輸出只含 global_hooks／global_mcp／global_plugins 的固定狀態與數量，不含自訂 hook／server／plugin 名稱、命令、環境變數、URL、headers、token 或設定值。只讀三處共用設定，不讀登入檔，也不執行 agy、hooks 或 MCP。新版生成前的錯誤診斷也會帶 extension_checks。

- review_required:false：本次掃描未發現需審查的共用擴充；這不是 Google 帳號生圖授權的證明。可重啟 Gateway 再執行一次 Gemini 圖片 PoC。
- global_hooks 的 enabled_handler_count > 0：有會被載入的 hook handler。官方 hooks 可在 SessionStart 執行命令，發生在模型工具權限檢查之前；不能只靠 mcp／command deny 假設它不會執行。
- global_mcp 的 enabled_server_count > 0：有未明確停用的 MCP server，連線時可能啟動本機程序。可以先在本機 agy 的 MCP 管理介面檢視；不要為了生圖清空所有設定。
- global_plugins 的 candidate_count > 0：有非空 plugin 目錄，尚未獨立確認其啟用狀態與內容。原生 agy plugin list --json 可在使用者本機查看，但不要分享整份輸出，可能包含私人名稱與路徑。
- unknown_entry_count > 0 或 invalid／unreadable／symlink：未知格式或不能安全檢查，仍明確停止；先分享去敏摘要再決定下一步。

本輪未找到已驗證的「僅本次停用全部共用 hooks／plugins」CLI 選項，因此沒有把 settings.json 的 hooks:{} 當成停用開關（官方 schema 明確表示該欄位不會被 CLI 載入），也沒有搬移／覆寫使用者共用設定。真正的執行項仍待實際本機摘要確認，並非宣稱這次生成失敗已解決。

Python 71/71 測試通過，涵蓋空／停用／啟用項、畸形或過大檔案、symlink 拒絕、雜項檔案、不輸出私人欄位、擋下時不執行 CLI、允許時使用原生圖片 session 且共用設定位元組不變。離線腳本亦已在雲端執行確認輸出合約；使用者的真實共用設定仍待本機結果。


## MCP 檔案 unreadable_or_invalid：JSONC 相容與精確分類

使用者最新離線摘要已確認只有 global_mcp 阻擋，hooks／plugins 均 inactive。舊版把讀取錯誤、編碼與 JSON 語法失敗合併為 unreadable_or_invalid，無法判斷是否真的有擴充啟用。

重新核對 [官方 CLI CHANGELOG](https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md)：1.1.24 支援 MCP 檔案的 //、/* */ 註解與尾端逗號；1.3.1 支援 MCP／hooks／plugin manifest 的 UTF-8 BOM。Gateway 原本使用嚴格 JSON，可能誤擋合法設定。新版只在記憶體中正規化 MCP JSONC，保留字串與 URL、命令中的 // 或 /* 字面內容，不改寫檔案。hooks 只新增有官方證據的 BOM 支援，未將 MCP 的 JSONC 規則直接套用至 hooks。

解析後仍檢查實際 MCP server 與 disabled:true。重複鍵、NaN／Infinity、單引號／未加引號 key 等一般 JSON5 語法、未閉合註解與缺值仍拒絕，不會當成空 MCP。檔案最多 1 MiB、巢狀最多 128 層，不跟隨檔案 symlink。

先更新後執行同一支離線指令，不需要再次生成：

```bash
git pull --ff-only
python3 scripts/antigravity-diagnostic.py
```

新 global_mcp 摘要視情況提供 size_bytes、utf8_bom、format=json/jsonc、數字 read_errno、json_error_line／json_error_column，仍不提供原文、parser 訊息或檔案內容。

| state | 解讀 |
|---|---|
| inactive 且 review_required:false | 設定可解析，沒有啟用中的 server。重新啟動 Gateway 後才執行圖片 PoC。 |
| read_permission_denied | OS 回 EACCES／EPERM；不是 JSON 語法錯誤。 |
| read_error | 其他 OS 讀取錯誤，以數字 read_errno 協助定位。 |
| empty_file | 空檔案或只有空白，不直接當成有效空 MCP 設定。 |
| invalid_utf8 | 編碼不是可解碼的 UTF-8。 |
| invalid_json | JSON／JSONC 語法或重複鍵問題；能定位時會附行、列。 |
| invalid_root_type | JSON 最外層不是 object。 |
| json_too_deep／invalid_or_oversized | 超過本機解析限制或不是一般檔案。 |

如果仍 review_required:true，先分享新版 global_mcp 區段，無須分享檔案原文。沒有依據時不清空使用者設定，也不改權限或讀取登入憑證。本輪已修正可驗證的官方格式相容差異，仍未取得使用者實際檔案格式與讀取錯誤，不能宣稱真正阻擋原因已確認。

Python 77/77 通過，新增 JSONC／BOM、字串與 URL 原樣保留、啟用 server 不被忽略、空檔／編碼／語法／權限／深度分類、重複鍵／錯誤逗號／非 JSON 常數拒絕，既有生成流程的測試亦使用帶註解與尾端逗號的停用 MCP 設定，確認檔案位元組不變。未呼叫提供者生成。


## 已更新 CLI 仍報 update_cli_for_session_settings：help 輸出通道修正

官方 agy 1.4.12 的 --help 成功退出，但 stdout 為 0 bytes，說明文字包含 --settings 全在 stderr。已用 SHA512 校驗過的官方 Linux binary 重現：stderr 3048 bytes。舊 Gateway 只收 stdout，會把新版也誤判成不支援本次設定；這是 Gateway 的能力檢查錯誤，不是 Google 帳號或生圖額度判定。

新版只對兩個參數的獨立 CLI --help 探測合併 stdout／stderr，並匹配真正以 --settings 開始的選項行；說明中的錯誤句或 --settings-file 不算支援。合併模式不允許 login、額外參數、payload 或 prompt，且保留輸出大小／時間限制。一般文字、生成及 capture_exit 流程仍不回傳 stderr，診斷不保存原始說明或錯誤內容。

不需要因這次誤判先重裝或重登。停止舊 Gateway，git pull --ff-only 後重啟，再執行原 Gemini 圖片 PoC。若修正後仍回同樣代碼，才表示 Gateway 實際呼叫到的 CLI 說明中沒有該選項；可先用官方 agy update 更新並重啟 Gateway。

80 項 Python 測試通過，新增真實子程序把 help 選項輸出到 stderr 的回歸、非 help 捕捉拒絕、成功生成也不回傳 stderr。另以官方 agy 1.4.12 經新版 run_bounded 實際檢查，session_settings_supported:true；沒有登入或呼叫提供者生圖，因此仍待 Mac Ultra 生成結果。
