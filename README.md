# 電子敲木魚

手機版 FastAPI 敲木魚遊戲，供課堂網路流量監控實驗使用。A、B 伺服器使用同一份程式碼，透過 `.env` 設定隊伍與各自獨立的 SQLite 資料庫。

## 本機啟動

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

瀏覽 `http://127.0.0.1:8000/`。API 可用 `GET /health`、`GET /api/config`、`GET /api/stats?player_id=...` 與 `POST /api/tap`。

頁面右下角會顯示 `VERSION` 與執行中 Git Commit 短 SHA。`GET /api/version` 也會回傳相同資訊；Git 資訊無法取得時會顯示 `unknown`，不會使用假 SHA。

玩家敲擊音效目前使用專案內的 `app/static/assets/woodfish-hit.wav`，透過點擊事件內的 HTML media `play()` 播放，不使用通知 API 或 Web Audio oscillator。音效開關暫時隱藏，待手機媒體音量與相容性驗證完成後再恢復。

### Zabbix HTTP 敲擊請求監控

每台 Game Server 提供唯讀 `GET /api/metrics`。回應中的 `tap_requests_total` 是該台伺服器實際收到的 `POST /api/tap` HTTP 請求累積數，包含成功、失敗、重複與請求格式驗證失敗；它不是功德數、TCP 封包數或流量 Bytes。

```json
{
  "team_id": "A",
  "tap_requests_total": 1234,
  "server_time": "2026-11-03T14:00:00Z"
}
```

Zabbix 7.0 LTS 可在 A、B 主機各建立 HTTP agent item：

- URL：`http://127.0.0.1:8000/api/metrics`（在各 Game Server 本機監控時）
- Type of information：Numeric (unsigned)
- Preprocessing：JSONPath `$.tap_requests_total`
- Units：`req`
- Storage/速率：使用 **Change per second**（或在圖表中選每秒變化）得到 Requests/s

若由 VM 1 監控，URL 改為 `http://192.168.26.133:8000/api/metrics` 與 `http://192.168.26.135:8000/api/metrics`。請確保 Ubuntu 防火牆只允許監控來源；此 API 只讀、不改變玩家 API。

計數器儲存在各自 SQLite 的 `game_state.tap_requests_total`，並以 SQLite 交易更新，可處理並行請求。服務重啟不會歸零；只有刪除/重建資料庫才會歸零。管理頁面的「重設功德」不會重設此 HTTP 請求計數器。

## 回合管理

管理指令只在伺服器本機執行，不提供公開重設 API：

```bash
python scripts/manage_round.py start --name "第一回合"
python scripts/manage_round.py pause
python scripts/manage_round.py reset
python scripts/manage_round.py end
```

`reset` 只清除本回合計數，保留全隊與個人累積；`start` 會開始新回合並清除本回合計數。

## A/B 集中管理

目前管理頁面由 Ubuntu-Monitor（VM 1，`192.168.26.131:8010`）提供。瀏覽器只連 VM 1，管理服務再透過內部網路呼叫 Game-Server-A（`192.168.26.133:8000`）與 Game-Server-B（`192.168.26.135:8000`）；瀏覽器不直接呼叫兩台遊戲伺服器的管理 API。

管理頁面可顯示兩隊真實狀態、全隊功德、回合功德、近 60 秒敲擊速率、連線狀態與部署 Commit，並支援個別或同時開始、暫停、繼續、結束與重設功德。共同操作會分別回報 A/B 結果；只有一隊成功時會顯示部分成功。重設需要瀏覽器確認，且會清除該隊全隊功德、回合功德、所有玩家個人功德與已處理的敲擊識別碼，因此所有手機下一次輪詢都會看到 0。

Game Server 的管理 API 只接受 `ADMIN_PROXY_IP`（預設 `192.168.26.131`）來源，避免玩家端直接控制回合。這不是登入驗證；集中管理無帳號密碼是課堂實驗的已知風險。

### VM 1 安裝管理服務

以下只應在 VM 1 執行，不會修改既有 `woodfish`、Zabbix、ntopng 或 `cloudflared` 服務：

```bash
cd /home/labuser/woodfish-game
cp .env.admin.example .env.admin
sudo cp systemd/woodfish-admin.service.example /etc/systemd/system/woodfish-admin.service
sudo systemctl daemon-reload
sudo systemctl enable --now woodfish-admin
sudo systemctl status woodfish-admin
curl -sS http://127.0.0.1:8010/health
```

管理頁面在未設定 Cloudflare Route 前可由內網使用：`http://192.168.26.131:8010/`。8010 不使用 Zabbix HTTP、ntopng 的 3001，也不改動現有 Tunnel。若要公開，建議另設 `admin-woodfish-a.netplaylab.codes` 指向 VM 1 的 `http://127.0.0.1:8010`，但必須由管理者自行修改 Cloudflare Tunnel route。

### 管理服務更新與驗證

```bash
cd /home/labuser/woodfish-game
git pull --ff-only origin main
.venv/bin/pip install -r requirements.txt
sudo systemctl restart woodfish-admin
curl -sS http://127.0.0.1:8010/api/admin/status
sudo journalctl -u woodfish-admin -n 50 --no-pager
```

若 A 或 B 離線，頁面會保留另一隊實際資料並明確顯示離線；不會使用模擬值。

## 測試與負載測試

```bash
python -m pytest
```

正式網址禁止直接壓測。只對本機或已獲授權的環境執行：

```bash
python scripts/load_test.py --url http://127.0.0.1:8000 --requests 100 --concurrency 10
```

工具會輸出成功率與延遲；每次有效敲擊都是一個獨立 POST，伺服器用 `tap_id` 去重。

## Ubuntu 部署

兩台 VM 各自執行以下步驟，A 使用 `TEAM_ID=A`，B 使用 `TEAM_ID=B`；不要共用資料庫：

```bash
git clone <GitHub-Repository-URL> /home/labuser/woodfish-game
cd /home/labuser/woodfish-game
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
editor .env
```

先備份並停止既有測試服務，再安裝本專案提供的範本：

```bash
sudo cp /etc/systemd/system/woodfish.service /etc/systemd/system/woodfish.service.bak.$(date +%Y%m%d%H%M%S)
sudo systemctl stop woodfish
sudo cp systemd/woodfish.service.example /etc/systemd/system/woodfish.service
sudo systemctl daemon-reload
sudo systemctl enable --now woodfish
sudo systemctl status woodfish
```

更新：

```bash
cd /home/labuser/woodfish-game
git pull --ff-only origin main
.venv/bin/pip install -r requirements.txt
sudo systemctl restart woodfish
sudo journalctl -u woodfish -f
```

部署後驗證版本與快取：

```bash
cd /home/labuser/woodfish-game
git rev-parse --short HEAD
curl -sS http://127.0.0.1:8000/api/version
curl -sSI http://127.0.0.1:8000/
curl -sS https://woodfish-a.netplaylab.codes/api/version
curl -sS https://woodfish-b.netplaylab.codes/api/version
```

`git rev-parse --short HEAD` 必須與本機 `/api/version` 的 `commit` 相同；兩台伺服器的 API 回應可用來確認部署是否一致。HTML 使用 no-store，CSS、JavaScript 與圖片 URL 使用部署版本作為 cache-busting token。

服務固定監聽 `8000`，不使用 `8100`；Cloudflare 路由、Zabbix、ntopng 不需修改。SQLite 備份可在停止服務後複製 `.env` 指定的資料庫檔案，重設資料庫前請先備份。

## 監控解讀

Zabbix 可觀察遊戲伺服器介面的 inbound/outbound、CPU、記憶體與可用的 packet rate。ntopng 能看到的端點與協定取決於 NAT、VMware 與 Cloudflare Tunnel；程式的 HTTP request 次數不等於網路封包數，也不代表能看到玩家原始 IP。請依實際監控畫面記錄結果。

`/api/metrics` 的 `tap_requests_total` 是應用層收到的 HTTP `POST /api/tap` 請求數；Zabbix 的 Change per second 是 Requests/s，不等於 TCP 封包速率或網路流量 Bytes/s。

## Git

```bash
git init
git add .
git commit -m "feat: initialize woodfish game"
git branch -M main
git remote add origin <GitHub-Repository-URL>
git push -u origin main
```

建議使用 `feature/*` 分支，測試後合併至 `main`；不要提交 `.env`、虛擬環境或 SQLite 資料庫。
