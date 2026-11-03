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
- Web Audio 木魚音效與音效開關。
- FastAPI、SQLite、回合 CLI 管理及基本自動化測試。
- 相對 API 路徑，適合 Cloudflare Tunnel 部署。
- Zabbix/ntopng 流量監控實驗用途的部署文件與負載測試工具。

### 待驗證

- iPhone Safari/Chrome 實機音效播放，尤其首次觸控與靜音狀態。
- 兩台 Ubuntu VM 重新部署後的 `/api/version` SHA 是否一致。
- Cloudflare Tunnel 下手機重新整理是否取得最新 HTML、CSS、JavaScript。
- Zabbix 與 ntopng 實際可觀察到的流量、協定與封包限制。

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
