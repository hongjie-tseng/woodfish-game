# 電子敲木魚永久需求

## 版本識別與部署驗證

- 每個遊戲頁面必須顯示目前部署版本。
- 顯示專案版本號與 Git Commit 短 SHA，例如 `v0.1.0 · a3f82c1`。
- 版本資訊必須由後端提供，不得硬編碼假的部署 Commit。
- 專案版本號集中管理於根目錄 `VERSION`。
- Git 資訊無法取得時，Commit 顯示 `unknown`。
- `GET /api/version` 必須回傳目前執行版本與實際 Git Commit。

## 部署與 Git 管理

- Windows VS Code 負責開發。
- GitHub `main` 為穩定部署來源。
- Game-Server-A 與 Game-Server-B 使用相同程式碼。
- A、B 伺服器透過各自 `.env` 設定區分。
- 每次修改後必須先 Commit、Push，再由 VM 執行 Git Pull 更新。
- 版本資訊用於確認不同 VM 是否部署相同 Commit。

## 快取管理

- HTML 頁面與 `/api/version` 必須避免使用過期快取。
- CSS、JavaScript 與圖片資源使用部署版本作為 cache-busting token。
- 新版本部署後，手機重新整理必須能取得新版前端資源。
- 不得以關閉所有靜態資源快取取代版本化快取。
- 專案不得依賴 Service Worker；目前沒有 Service Worker。

## 原有遊戲需求與目前狀態

### 已實作

- Vanilla JavaScript、HTML、CSS 的手機敲木魚遊戲。
- A、B 隊各自使用獨立 SQLite 計數。
- 每次敲擊發送一個真實 `POST /api/tap`，使用唯一 `tap_id`。
- 個人功德、全隊功德與連線狀態。我的功德由手機計算並存在 localStorage，伺服器最終拒絕的敲擊會扣回；全隊功德來自伺服器，同一次重設內只增不減；回應中的 `reset_marker` 變大時手機歸零。
- 和尚揮槌動畫：大和尚手臂揮下、小和尚與木魚受擊壓縮回彈、敲擊線閃動，約 40 ms 內敲中以配合音效；支援減少動態效果設定。圖層由 `scripts/build_monk_layers.py` 產生。
- 功德浮動文字。
- Web Audio 播放本地 WAV 木魚音效；iOS 17 以上使用 `navigator.audioSession.type = "playback"` 走媒體音量，鎖螢幕或切換 App 後下次觸控自動恢復。
- 音色選單（暫時）：小／中／大木魚與原本音效，供測試者選出最終音效後移除。音效由 `scripts/make_woodfish_sound.py` 合成。
- FastAPI、SQLite、回合 CLI 管理及基本自動化測試。
- 相對 API 路徑，適合 Cloudflare Tunnel 部署。
- Zabbix/ntopng 流量監控實驗用途的部署文件、負載測試與逐級加壓測試工具（`scripts/stress_test.py`）。
- 每台 Game Server 提供唯讀 `GET /api/metrics`，以 `tap_requests_total` 統計實際收到的 `POST /api/tap` 請求，包含成功、失敗、重複與格式驗證失敗。
- 高流量架構：敲擊在記憶體累計、每 0.5 秒批次寫入 SQLite，A、B 各 3 個 Uvicorn worker；2026-11-04 內網實測每台每秒 2000 次通過（p95 約 30 ms）。
- 兩台 VM 的 SSH 自動部署（`scripts/deploy.ps1`），部署後 `/api/version` 與前端資源版本已確認一致。

### 待驗證

- iPhone Safari/Chrome 實機：靜音開關開啟時是否走媒體音量發聲、鎖螢幕後是否恢復（需要 iOS 17 以上）。
- 測試者選出最終木魚音效。
- Zabbix 與 ntopng 實際可觀察到的流量、協定與封包限制。
- Zabbix HTTP agent 以 JSONPath `$.tap_requests_total` 讀取計數器，並以 Change per second 顯示 Requests/s。
- 經 Cloudflare 時 VM 1 cloudflared 的實際上限（估計兩台合計每秒 2500–3500 次；需由 VM 以外的電腦送出請求才能準確量測）。

### 已知限制

- 斷電或程式當機最多遺失最後 0.5 秒的敲擊；正常重啟或部署不會遺失。這是課堂展示接受的取捨。
- 我的功德存在每支手機上，換手機、換瀏覽器或清除網站資料會重新計算。
- 敲擊動畫中，前臂與下方衣褶交界在敲中瞬間有小缺口；木魚周圍淡灰色與小和尚額頭白線是原始素材本來就有的瑕疵，不處理。

## 部署驗收

在每台 VM 執行：

```bash
cd /home/labuser/woodfish-game
git rev-parse --short HEAD
curl -sS http://127.0.0.1:8000/api/version
curl -sSI http://127.0.0.1:8000/
```

`git rev-parse --short HEAD` 必須與 `/api/version` 的 `commit` 相同。外部網址也應檢查：

```bash
curl -sS https://woodfish-a.netplaylab.codes/api/version
curl -sS https://woodfish-b.netplaylab.codes/api/version
```

回傳的 `version` 與 `commit` 可用來確認兩台伺服器是否執行相同版本。

## HTTP 敲擊請求監控需求

- A、B 各自提供 `GET /api/metrics`，資料來自各自 SQLite，不需要同步。
- JSON 至少包含 `team_id`、`tap_requests_total` 與 `server_time`。
- `tap_requests_total` 是實際進入應用程式的 `POST /api/tap` 請求總數，包含成功、失敗、重複與 Pydantic 請求格式驗證失敗；不可用功德數代替。
- 計數器先在各 worker 記憶體累計，每 0.5 秒以 SQLite 交易批次寫入；`/api/metrics` 讀 SQLite，因此最多延遲 0.5 秒，但在多個 worker 下仍保證只增不減。服務重啟後保留，刪除/重建資料庫才歸零。
- 每個請求的 Uvicorn 存取紀錄關閉，以免高流量時日誌耗用的 CPU 超過遊戲本身。
- Zabbix 7.0 LTS 使用 HTTP agent 讀取 `/api/metrics`，JSONPath `$.tap_requests_total`，再使用 Change per second 計算 Requests/s。
- 這是 HTTP 應用層請求數，不是 TCP 封包數、封包速率或網路流量 Bytes；ntopng/Zabbix 網路流量圖表需分開解讀。
- 管理頁面的功德重設不得清除 `tap_requests_total`。

## A/B 集中管理需求

- Ubuntu-Monitor（VM 1，`192.168.26.131`）提供唯一的集中管理頁面，管理服務使用 Port `8010`。
- Game-Server-A/B 維持 Port `8000` 與各自獨立的 SQLite；不新增 VM、Docker、Redis 或額外資料庫。
- 瀏覽器只能呼叫 VM 1 管理服務；VM 1 後端透過內部網路轉送至 A/B，瀏覽器不得直接呼叫 Game Server 管理 API。
- 管理頁面每秒更新，必須顯示 A/B 真實狀態、全隊功德、回合功德、近期敲擊速率、近 5 秒每秒點擊與每秒請求、累計請求（重設後，以 `tap_requests_total - tap_requests_reset_base` 計算）、連線狀態與各自 Commit；只更新數字，不在按鈕操作時重畫按鈕。
- 每隊及共同操作都必須支援開始、暫停、繼續、結束與重設功德；重設必須確認。
- 管理頁的重設功德必須在目標伺服器交易中清除全隊功德、回合功德、所有玩家個人功德與已處理敲擊識別碼，讓所有玩家下一次取得統計時看到 0。
- 共同操作必須分別確認兩台伺服器結果；只有一隊成功時顯示部分成功，不得假裝全部完成。
- 管理 API 不使用帳號密碼登入是已知且接受的課堂實驗風險；Game Server 管理 API 僅接受 VM 1 的 `ADMIN_PROXY_IP` 來源。
- 管理服務不得占用或修改 Zabbix、ntopng（Port 3001）及 Cloudflare Tunnel；管理頁面只在內網使用，因為沒有登入驗證，不得建立公開的 Cloudflare route。
- VM 1 管理服務使用 `systemd/woodfish-admin.service.example`，獨立於既有 `woodfish.service`。
- 近期敲擊速率由 VM 1 對真實伺服器回報的計數樣本計算，存於管理服務記憶體；服務重啟後先顯示待建立樣本，不使用模擬值。

## 管理操作稽核日誌

- A、B 各自的 SQLite 使用 `admin_audit_logs` 保存操作紀錄，資料不跨伺服器同步。
- 管理 API 的 `start`、`pause`、`resume`、`end`、`reset`、拒絕的狀態操作，以及 `system_startup` 和 CLI `internal` 操作都必須記錄。
- 欄位包含 `id`、UTC `timestamp`、`team_id`、`action`、`previous_status`、`new_status`、`source`、`source_ip`、`success`、`error_message`、`git_commit` 與 `state_initialized`。
- 狀態更新與成功稽核紀錄在同一 SQLite transaction；拒絕操作也會先提交失敗紀錄，再回傳 HTTP 409。
- FastAPI 啟動只讀取 SQLite 已保存的回合狀態並記錄 `system_startup`，不會無條件套用 `.env` 的 `ROUND_STATUS`。
- `GET /api/admin/audit-logs?limit=50` 是唯讀查詢，limit 範圍為 1 到 200，依時間新到舊排序；VM 1 的同名 API 會合併 A、B 最近事件。
- 日誌最多保留 10,000 筆；重設功德只清除功德、玩家與已處理敲擊資料，不清除稽核日誌或 `tap_requests_total`。
- 排查遊戲停止計數時，先查詢最後事件的 `source`、`action` 與狀態轉換；`admin_api` 是集中管理操作，`system_startup` 是服務啟動，`internal` 是 CLI 或程式內部操作。
- 正式部署前應停止服務並備份 `woodfish.db`；migration 只建立表格/索引與必要欄位，不得刪除、重建或單獨刪除 SQLite 的 `-wal`、`-shm` 檔案。還原前也必須先停止服務並保留正確擁有者。

## 三台 VM SSH 自動部署需求

- Windows VS Code 為部署控制端；GitHub `main` 是唯一部署來源。
- `scripts/check-servers.ps1` 必須以 SSH 唯讀查詢 `woodfish-a`、`woodfish-b`、`woodfish-monitor` 的 Git Commit、工作目錄、systemd 狀態與 Health。
- `scripts/deploy.ps1` 預設只檢查；只有明確傳入 `-Deploy` 才能更新遠端。
- 部署順序固定為 Game-Server-A、Game-Server-B、Ubuntu-Monitor。
- 部署前必須確認本機 `main` 工作樹乾淨、HEAD 已 Push 至 `origin/main`，每台遠端工作樹乾淨且可取得預期 Commit。
- 部署只允許 `git pull --ff-only origin main`、更新既有 venv requirements、重啟對應既有 systemd，並逐台驗證 Commit、服務 active、Health 與 A/B `TEAM_ID`。
- 不得修改 `.env`、`.env.admin`、SQLite、Cloudflare、Zabbix、ntopng；不得使用 `git reset --hard`、`git push --force` 或 `apt upgrade`。
- 遠端有未提交修改、SSH/Git/依賴/重啟/Health 失敗時必須停止並明確報告。
- A、B 的 `woodfish.service` 以 systemd drop-in `/etc/systemd/system/woodfish.service.d/workers.conf` 執行 3 個 Uvicorn worker，不修改原本的服務檔；每次重啟會有 3 筆 `system_startup` 稽核紀錄。
- 三台 VM 必須只對指定服務設定 NOPASSWD：A/B 使用 `woodfish.service`，Monitor 使用 `woodfish-admin.service`。部署腳本所有 SSH 使用 `BatchMode=yes`，部署前以 `sudo -n /usr/bin/systemctl show <service> --property=LoadState --value` 唯讀驗證權限，重啟只允許 `sudo -n /usr/bin/systemctl restart <service>`。不得使用 `sudo -S`、標準輸入傳密碼或互動式 SSH。
