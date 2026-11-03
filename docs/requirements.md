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
- 個人功德、全隊功德與連線狀態。
- 木魚受擊壓縮/回彈動畫與功德浮動文字。
- 本地 WAV 木魚音效，透過 HTML media 播放；音效開關目前暫時隱藏，待手機媒體音量與相容性驗證完成後恢復。
- FastAPI、SQLite、回合 CLI 管理及基本自動化測試。
- 相對 API 路徑，適合 Cloudflare Tunnel 部署。
- Zabbix/ntopng 流量監控實驗用途的部署文件與負載測試工具。
- 每台 Game Server 提供唯讀 `GET /api/metrics`，以 `tap_requests_total` 統計實際收到的 `POST /api/tap` 請求，包含成功、失敗、重複與格式驗證失敗。

### 待驗證

- iPhone Safari/Chrome 實機媒體音效播放，尤其首次觸控、媒體音量與靜音狀態。
- 兩台 Ubuntu VM 重新部署後的 `/api/version` SHA 是否一致。
- Cloudflare Tunnel 下手機重新整理是否取得最新 HTML、CSS、JavaScript。
- Zabbix 與 ntopng 實際可觀察到的流量、協定與封包限制。
- Zabbix HTTP agent 以 JSONPath `$.tap_requests_total` 讀取計數器，並以 Change per second 顯示 Requests/s。

### 尚未完成

- 乾淨手臂/手掌/槌子分層素材不足，因此尚未實作安全的和尚揮槌動畫。
- 尚未完成兩台 VM 的每次部署自動化與正式效能驗證。

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
- 計數器使用 SQLite 持久化交易更新，可處理並行請求；服務重啟後保留，刪除/重建資料庫才歸零。
- Zabbix 7.0 LTS 使用 HTTP agent 讀取 `/api/metrics`，JSONPath `$.tap_requests_total`，再使用 Change per second 計算 Requests/s。
- 這是 HTTP 應用層請求數，不是 TCP 封包數、封包速率或網路流量 Bytes；ntopng/Zabbix 網路流量圖表需分開解讀。
- 管理頁面的功德重設不得清除 `tap_requests_total`。

## A/B 集中管理需求

- Ubuntu-Monitor（VM 1，`192.168.26.131`）提供唯一的集中管理頁面，管理服務使用 Port `8010`。
- Game-Server-A/B 維持 Port `8000` 與各自獨立的 SQLite；不新增 VM、Docker、Redis 或額外資料庫。
- 瀏覽器只能呼叫 VM 1 管理服務；VM 1 後端透過內部網路轉送至 A/B，瀏覽器不得直接呼叫 Game Server 管理 API。
- 管理頁面必須顯示 A/B 真實狀態、全隊功德、回合功德、近期敲擊速率、連線狀態與各自 Commit。
- 每隊及共同操作都必須支援開始、暫停、繼續、結束與重設功德；重設必須確認。
- 管理頁的重設功德必須在目標伺服器交易中清除全隊功德、回合功德、所有玩家個人功德與已處理敲擊識別碼，讓所有玩家下一次取得統計時看到 0。
- 共同操作必須分別確認兩台伺服器結果；只有一隊成功時顯示部分成功，不得假裝全部完成。
- 管理 API 不使用帳號密碼登入是已知且接受的課堂實驗風險；Game Server 管理 API 僅接受 VM 1 的 `ADMIN_PROXY_IP` 來源。
- 管理服務不得占用或修改 Zabbix、ntopng（Port 3001）及 Cloudflare Tunnel；目前不自行新增 Cloudflare 公開 route。
- VM 1 管理服務使用 `systemd/woodfish-admin.service.example`，獨立於既有 `woodfish.service`。
- 近期敲擊速率由 VM 1 對真實伺服器回報的計數樣本計算，存於管理服務記憶體；服務重啟後先顯示待建立樣本，不使用模擬值。

## 三台 VM SSH 自動部署需求

- Windows VS Code 為部署控制端；GitHub `main` 是唯一部署來源。
- `scripts/check-servers.ps1` 必須以 SSH 唯讀查詢 `woodfish-a`、`woodfish-b`、`woodfish-monitor` 的 Git Commit、工作目錄、systemd 狀態與 Health。
- `scripts/deploy.ps1` 預設只檢查；只有明確傳入 `-Deploy` 才能更新遠端。
- 部署順序固定為 Game-Server-A、Game-Server-B、Ubuntu-Monitor。
- 部署前必須確認本機 `main` 工作樹乾淨、HEAD 已 Push 至 `origin/main`，每台遠端工作樹乾淨且可取得預期 Commit。
- 部署只允許 `git pull --ff-only origin main`、更新既有 venv requirements、重啟對應既有 systemd，並逐台驗證 Commit、服務 active、Health 與 A/B `TEAM_ID`。
- 不得修改 `.env`、`.env.admin`、SQLite、Cloudflare、Zabbix、ntopng；不得使用 `git reset --hard`、`git push --force` 或 `apt upgrade`。
- 遠端有未提交修改、SSH/Git/依賴/重啟/Health 失敗時必須停止並明確報告。
- sudo 密碼不得寫入腳本；預設使用 `sudo -n`，需要密碼時由操作人使用 `-InteractiveSudo` 在 SSH 終端輸入。
