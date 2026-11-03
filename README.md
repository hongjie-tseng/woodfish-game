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

## 回合管理

管理指令只在伺服器本機執行，不提供公開重設 API：

```bash
python scripts/manage_round.py start --name "第一回合"
python scripts/manage_round.py pause
python scripts/manage_round.py reset
python scripts/manage_round.py end
```

`reset` 只清除本回合計數，保留全隊與個人累積；`start` 會開始新回合並清除本回合計數。

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

服務固定監聽 `8000`，不使用 `8100`；Cloudflare 路由、Zabbix、ntopng 不需修改。SQLite 備份可在停止服務後複製 `.env` 指定的資料庫檔案，重設資料庫前請先備份。

## 監控解讀

Zabbix 可觀察遊戲伺服器介面的 inbound/outbound、CPU、記憶體與可用的 packet rate。ntopng 能看到的端點與協定取決於 NAT、VMware 與 Cloudflare Tunnel；程式的 HTTP request 次數不等於網路封包數，也不代表能看到玩家原始 IP。請依實際監控畫面記錄結果。

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
