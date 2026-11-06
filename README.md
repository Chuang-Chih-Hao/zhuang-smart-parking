# 莊停車場 Smart Parking

**四車位 × 單一雙向出入口 × 7 感測點 × Flask × ESP32 MicroPython × Render**

這份專案提供可執行的網站及後端：模擬車位、A/B 方向事件、閘門開關、防夾、安全白名單、車輛進出紀錄、公開剩餘車位看板，以及供未來 ESP32 使用的 HTTP JSON API。前端採響應式暗色管理儀表板；網站與 API 由 **同一個 Flask 程序**提供，不需要再另外部署 GitHub Pages。

> **完成程度**：Flask 網站、資料庫模型、API、前端模擬、核心單元測試已實作。`firmware/` 為待接線的 ESP32 **參考程式**，GPIO 尚未指定；USB 攝影機的實際 OCR 尚未實作，`camera_agent/send_plate.py` 只提供辨識結果的上傳接點。**本專案是課堂比例模型，不能未經額外安全認證用於真實車輛閘門。**

## 1. 專案架構

```text
zhuang-smart-parking/
├─ app.py                    Flask 路由、管理員登入、CSRF、設備 API
├─ parking/
│  ├─ core.py                方向狀態機、進出場、車位容量、安全限制
│  └─ models.py              SQLAlchemy 資料表（SQLite/PostgreSQL）
├─ templates/                管理控制台、登入頁、公開看板
├─ static/                   網頁 CSS / JavaScript
├─ firmware/                 MicroPython 感測器 / 伺服 / HTTP 範例
├─ camera_agent/             電腦端「已辨識車牌」上傳範例
├─ tests/                    核心、Flask API 測試
├─ .github/workflows/ci.yml  推送時自動執行測試
├─ render.yaml               Render Web Service Blueprint
├─ .env.example              本機環境變數範例（不含真實密碼）
└─ requirements.txt
```

資料流：

```text
P1 P2 P3 P4 + A + B + S (7 sensors)
                │
      ESP32 / MicroPython
                │ POST /api/device/events and /state
             Flask API  ←  Camera agent (already recognized plate)
                │
       SQLAlchemy / Database
                │
     Admin dashboard / Public display
```

- **P1–P4**：每個車位的占用訊號。
- **A**：外側方向感測；**B**：內側方向感測。
- **S**：閘門防夾，與方向判斷獨立，不能省略或兼用。
- **A → B**：候選進場；**B → A**：候選離場。
- 要在「車牌已驗證、閘門已開啟、方向順序正確、A/B/S 清空」後，系統才建立完整進出紀錄。
- 車位容量以 `4 - max(實體占用, 已完成進場且未離場) - 待入場預留數` 估算，再限制於 0–4。車位與在場紀錄不同時顯示警告。

### 單一共用出入口的限制

本系統預設模型車一次只通過一輛，並且每次只處理一筆通行。兩車緊跟（tailgating）、並行、倒車、對射遮蔽、感測器盲區及車牌辨識角度都需要額外測試；**只有 A/B 兩個點，不能保證所有複雜交通行為都能可靠判定**。MG90S 沒有實際位置回饋，因此網站的 `OPEN/CLOSED` 是馬達命令推定值，不是限位開關的實測結果。實際雙向攝影可能需要兩個拍攝方向或雙攝影機。

## 2. 在 Windows + VS Code 執行

先安裝 Python 3.11 或 3.12、VS Code。開啟本專案資料夾，在 VS Code 的 Terminal / PowerShell 輸入：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

若 `py -3.12` 無法找到，可改成電腦實際安裝的 `py -3.11` 或 `python -m venv .venv`。

用 VS Code 打開 `.env`，至少更改 `SECRET_KEY`、`ADMIN_PASSWORD`、`DEVICE_TOKEN` 和 `CAMERA_TOKEN`。**不要把 `.env` 上傳 GitHub**。在本機保留 `APP_ENV=development`、`SEED_DEMO=true`，可以使用範例車牌 `ABC-1234`、`DEF-5678`。

接著啟動：

```powershell
python app.py
```

打開：

- 管理員登入：`http://127.0.0.1:5000/login`
- 公開車位看板：`http://127.0.0.1:5000/display`
- 健康檢查：`http://127.0.0.1:5000/healthz`

本機資料庫預設是 `instance/parking.db`。首次啟動會自動建立資料表，重新啟動仍會保留資料。若早期測試版資料庫結構不同，**請先備份**再執行資料庫遷移或刪除舊測試 DB；`create_all` 不會自動變更舊表欄位。

PowerShell 若出現啟用政策錯誤，可直接使用：

```powershell
.\.venv\Scripts\python.exe app.py
```

## 3. 五分鐘模擬操作

1. 以 `.env` 中的 `ADMIN_PASSWORD` 登入。
2. 模擬模式會自動提供五組預設白名單：`ABC-1234`、`ABC-5333`、`DEF-5678`、`GHI-9012`、`JKL-3456`。新增自訂車牌也可以，但所有進出都必須先通過白名單驗證。
3. 在「感測器模擬」把 **A 外側**切成「已觸發」。
4. 在「通道監控」輸入 `ABC-1234` → **驗證車牌** → **開啟閘門**。
5. 回「感測器模擬」把 **B 內側**切成「已觸發」，然後依序把 **A、B** 清空。
6. 進場紀錄增加一筆，在場車輛 +1，剩餘車位 -1（預留數也會計算）。可以再把 P1 設成「有車」，模擬停入車位。
7. 返回「通道監控」按 **安全關閘**（必須 A、B、S 全部未觸發）。
8. **離場**時先觸發 B，對同一車牌驗證／開閘，再觸發 A，最後清空 B、A，完成離場。

**清空所有模擬資料**：進入「感測器模擬」使用此按鈕，會二次確認並清除 7 個感測器、閘門狀態、進出紀錄、系統事件、待處理命令以及自訂白名單，最後恢復五組預設示範車牌；**只能在 SIM 模式執行，不能復原，不會對實體硬體發送命令**。「重設感測器」仍保留原本的非破壞性操作，只重設感測器和閘門。

**未授權行為**：只觸發 A 或 B 不會開閘；沒有白名單驗證、車牌遭停用、輸入車牌與已驗證車牌不一致，均禁止開閘。預設示範車牌只允許 SIM 模式，切換 HARDWARE 後需自行明確建立或更新正式白名單。

**防夾測試**：開閘後把 S 切成「已觸發」，此時網頁關閘按鈕應收到拒絕回覆。**未授權通過**：在沒有驗證車牌／開閘的情況下，依序觸發 A、B，系統應顯示異常且不新增進出紀錄。

> 目前不會自動收取費用。停留時間會由 `entered_at` 和 `left_at` 計算；後續可另設收費規則。

## 4. 上傳新的 GitHub 儲存庫

**建議庫名：** `zhuang-smart-parking`，帳號可選 `Chuang-Chih-Hao`。

1. 至 <https://github.com/new> 建立 repository；**不勾選** Initialize this repository with a README（本專案已包含）。
2. 在本機解壓縮這份專案後，用 VS Code 開啟資料夾終端機，執行：

```powershell
git init
git add .
git commit -m "Initial smart parking Flask simulator and ESP32 API"
git branch -M main
git remote add origin https://github.com/Chuang-Chih-Hao/zhuang-smart-parking.git
git push -u origin main
```

若儲存庫名稱或帳號不同，請修改 `git remote add origin` 的網址。確認已建立 `.gitignore` 並且 **沒有將 `.env`、`instance/parking.db`、ESP32 Wi-Fi 密碼、API Token** 推上 GitHub。推送後 `.github/workflows/ci.yml` 會自動執行測試。

## 5. 部署 Render（方案 A）

1. 在 Render 登入，選擇 **New → Blueprint**，連接剛建立的 GitHub repository（含根目錄 `render.yaml`）。也可以使用 **New → Web Service** 連接同一 repo。
2. 選免費 Web Service 方案、Singapore 區域（YAML 已設定）。
3. `ADMIN_PASSWORD` 設定**至少 12 字元**的強密碼。`SECRET_KEY`、`DEVICE_TOKEN`、`CAMERA_TOKEN` 由 Blueprint 自動產生；**不要把它們寫回 GitHub**。
4. Blueprint 檢查部署計畫後，確認不會產生意外收費項目，再按部署。
5. 等待服務完成，打開 Render 提供的 `https://<service>.onrender.com/login`，用 `ADMIN_PASSWORD` 登入。`/display` 是不需要登入的公開看板。
6. 後續只要推送 GitHub `main`，Render 就會重新部署。請查看 Render Build Logs 和 Runtime Logs 確認成功。

若手動建立 Web Service，請設定：

| 設定 | 值 |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn --workers 1 --threads 4 --timeout 60 --bind 0.0.0.0:$PORT app:app` |
| Health Check | `/healthz` |
| APP_ENV | `production` |
| SECRET_KEY | 長隨機字串 |
| ADMIN_PASSWORD | 至少 12 字元強密碼 |
| DEVICE_TOKEN | 隨機秘密值 |
| CAMERA_TOKEN | 隨機秘密值 |

### 重要：正式記錄需要持久化 PostgreSQL

**Render 免費 Web Service 的本機硬碟是暫存的。** 預設 SQLite 只適合示範，服務重啟、休眠或重新部署後，停車紀錄可能消失。要持續保留白名單與進出資料，請在 Render 建立或連接一個受管理的 PostgreSQL，取得連線字串並在 Web Service 環境變數加入 `DATABASE_URL`（支援 `postgresql://...` / `postgres://...`），再重新部署。

Blueprint **不會自行建立付費資料庫**，避免額外收費；資料庫需要另外選定。Render 免費 PostgreSQL 有有效期限制，不能當永久資料庫。請依照 Render 當下顯示的方案費用與限制決定；勿將 PostgreSQL URL 提交 GitHub。

官方參考：<https://render.com/docs/deploy-flask>、<https://render.com/docs/blueprint-spec>、<https://render.com/docs/free>。

## 6. API 摘要

| HTTP | Path | 認證 | 功能 |
|---|---|---|---|
| GET | `/api/public/status` | 無 | 對外車位看板（不含車牌） |
| GET | `/api/status` | 管理員 session | 完整狀態及事件 |
| GET / POST | `/api/plates` | 管理員 session + 寫入 CSRF | 查詢／新增車牌 |
| DELETE | `/api/plates/<plate>` | 管理員 + CSRF | 停用車牌 |
| GET | `/api/records` | 管理員 session | 最近 150 筆進出紀錄 |
| POST | `/api/sim/sensors` | 管理員 + CSRF | 模擬感測器變化 |
| POST | `/api/sim/reset` | 管理員 + CSRF | 重設模擬訊號，不刪除歷史 |
| POST | `/api/sim/reset-all` | 管理員 + CSRF + `confirmation: RESET_SIM_ALL` | 清除全部模擬資料並恢復五組預設車牌 |
| POST | `/api/passage/authorize` | 管理員 + CSRF | 驗證車牌及預留通行 |
| POST | `/api/gate/open` / `close` | 管理員 + CSRF | 安全閘門命令 |
| POST | `/api/mode` | 管理員 + CSRF | 切換 SIM/HARDWARE |
| POST | `/api/device/events` | Bearer DEVICE_TOKEN | 邊緣變化事件，保留 A/B 順序 |
| POST | `/api/device/state` | Bearer DEVICE_TOKEN | 週期感測器快照與心跳 |
| GET | `/api/device/commands` | Bearer DEVICE_TOKEN | 裝置取得尚未 ACK 的控制命令 |
| POST | `/api/device/ack` | Bearer DEVICE_TOKEN | 回覆控制命令成功／失敗 |
| POST | `/api/camera/recognize` | Bearer CAMERA_TOKEN | 上傳已辨識車牌並嘗試授權 |
| GET | `/healthz` | 無 | Render 健康檢查 |

### 設備事件例子

**POST** `/api/device/events`，Header: `Authorization: Bearer <DEVICE_TOKEN>`；下列為 JSON Body：

```json
{"boot_id":"espboot20261106","sequence":17,"sensor":"A","detected":true}
```

ESP32 必須先完成事件上報，才能發送序號更大的週期快照。單張狀態快照本身無法判斷 A/B 先後順序。每次重新啟動都使用新的 `boot_id`，使伺服器能重置舊序列號及取消舊命令。

## 7. ESP32 MicroPython：現在不接線，未來使用方式

目前 `firmware/config_example.py` 中所有 GPIO 預設是 `None`，`firmware/main.py` 在腳位尚未指定時**直接拒絕啟動**。這是刻意設計：在確認感測器供電、輸出電壓、ESP32 GPIO 邊界、伺服馬達獨立電源及共地前，絕不能擅自讓 MG90S 運動。

未來確認硬體後：

1. `config_example.py` 複製成 `config.py`，依實際接線填入 7 個感測器 GPIO 與伺服馬達 GPIO。
2. `secrets_example.py` 複製成 `secrets.py`，填入 Wi-Fi、Render HTTPS 服務網址、Render `DEVICE_TOKEN`。
3. 確保 ESP32 MicroPython 已提供 `network`、`urequests`、PWM 等必要模組，確認 HTTPS/TLS 與憑證驗證能力。不同版本 MicroPython 的 TLS 驗證能力不同；**不得在未驗證 TLS 安全性的情況下，將正式控制 Token 經網路傳輸**。若能力不足，應使用受信任的本地閘道代為與 Render 溝通。
4. 先在脫離閘門連桿的情況測試 MG90S 轉角，再測 S 阻擋時絕不關閉。
5. 將程式上傳 ESP32，確認事件、心跳、命令 ACK，再於網頁切換 HARDWARE。

**硬體安全特別注意**：MG90S 無實際位置回授，`gate.state` 只是控制器推定；單一紅外線 S 也不具備真實停車場安全設備的冗餘保護。若網路斷線，**本地保護邏輯不能依賴 Flask**。本範例不能作為可直接投入實際車輛環境的認證控制器。

## 8. USB 攝影機與車牌辨識

Render 在雲端無法直接讀取你的 Windows USB 攝影機，因此 OCR 應在本機執行，再把辨識結果透過 HTTPS 傳給 Flask。`camera_agent/send_plate.py` 提供了結果上傳範例，**不包含實際影像辨識演算法**。首先要在通道 A 或 B 觸發後，再送對應車牌；伺服器會使用白名單或在場紀錄檢查方向授權。

PowerShell 示範（先設定與 Flask 一致的環境變數）：

```powershell
$env:PARKING_API_URL = "http://127.0.0.1:5000"
$env:CAMERA_TOKEN = "從你的 .env 讀取，不要發布"
python camera_agent/send_plate.py ABC-1234
```

正式部署時將 URL 改成 Render 的 HTTPS 網址。若攝影機只能看到同一側車牌，需要調整拍攝角度或新增第二個拍攝方向。

## 9. 測試

```powershell
python -m pip install pytest
python -m pytest -q
```

- `tests/test_core.py`：進場、離場、在場紀錄、容量、白名單、安全阻擋、反向、設備訊息序號等。
- `tests/test_flask_api.py`：登入、CSRF、裝置 Token、API 通行流程。
- 推送 GitHub 時會由 GitHub Actions 執行相同測試。

## 10. 後續待整合

- [ ] 確認新購內側方向感測器 B；依模型尺寸選擇 FC-51 或對射式。
- [ ] 確定 7 個感測點 GPIO、5V 伺服供電、防夾安全配置。
- [ ] 測試實際方向、倒車、緊跟、反光與遮蔽情況。
- [ ] 在本地 USB 攝影機上完成真實 OCR，辨識進出兩個方向的車牌。
- [ ] Render 接上可持久化的 PostgreSQL。
- [ ] 依測試結果補強事件重送、斷線重啟、閘門位置確認和安全硬體。

---

**授權與資料安全**：請勿公開真實使用者車牌與進出資料。白名單、進出紀錄只允許管理員存取；公開看板只回傳容量資訊。部署時請為 GitHub/Render 管理權限、密碼、Token 和資料保留週期制定管理方式。
