# KyLuat DauTu - MVP

Web app ho tro ky luat mua ban co phieu theo rule, khong theo cam xuc.

## Da trien khai

- FastAPI + SQLite (WAL mode)
- Dashboard web (template + CSS + JS)
- Form watchlist/positions dang bang UI dong ro rang (them/xoa tung dong), khong can nhap chuoi comma.
- Tach rieng 2 man hinh: list (`/stocks`) va chi tiet (`/stocks/{symbol}`), plus man cau hinh (`/settings`).
- Tach ro 2 man cau hinh:
  - Theo doi: `/settings/watchlist`
  - Nam giu: `/settings/holdings`
- Man theo doi khong co rule; chi dung de theo doi va nhan khuyen nghi mua/ban.
- Rule mua/ban theo ma nam o man nam giu.
- Man nam giu co them rule ty le tai san (vi du 50% tien mat / 50% co phieu):
  - neu ty le co phieu thap hon muc muc tieu => canh bao mua them
  - neu ty le co phieu cao hon muc muc tieu => canh bao giam bot
- Tren man list: hien thi phien gan nhat (1 ngay) va giai thich ro "Ngoai rong", "Tu doanh rong".
- Tren man chi tiet: co bang lich su 5/10/20 ngay gan nhat de theo doi xu huong.
- Co chuc nang so sanh 2-3 ma tren man list, va bang list uu tien theo watchlist kem ly do ro rang.
- Daily ETL 15:30 (du lieu thi truong, co ban, tin tuc)
- Daily advice 06:00 (deterministic first, AI-last)
- Chinh sach han che Gemini:
  - chi goi khi co material change
  - quota global/user moi ngay
  - state hash de tranh goi lap
  - fallback deterministic khi AI loi
- Log de debug:
  - `backend/logs/app.log`
  - `backend/logs/error.log`
  - moi request co `X-Request-ID`

## Chay bang 1 lenh (uu tien conda)

Tu thu muc goc project, chi can chay:

```bash
run.bat
```

Script se tu dong:

- uu tien conda (tao env `kyluat-dautu` neu chua co)
- cai dependencies neu chua co
- tao `backend/.env` tu `.env.example` neu chua co
- khoi dong server tai `http://localhost:8000`

Neu may chua co conda, script tu fallback sang `python venv`.

Tuy chon:

- Doi ten conda env: `run.bat -EnvName ten-env`
- Doi port: `run.bat -Port 9000`

## Chay ngam & Khoi dong cung he thong (Background Service)

He thong ho tro chay ngam (khong hien cua so terminal) va tu dong khoi dong khi co internet tren ca Windows va Linux.

### Tren Windows
1. **Chay ngam ngay lap tuc**: Click dup vao file `start_bg.bat` de chay background an hoan toan.
2. **Cai dat auto-start (Scheduled Task)**:
   - Mo **PowerShell voi quyen Administrator**
   - Chay file bang lenh: `.\install_service.ps1`
   - Server se tu dong chay ngam ngay khi ban mo may tinh va ket noi internet.

### Tren Linux (Ubuntu / Raspberry Pi / VPS)
1. **Chay ngam ngay lap tuc**:
   ```bash
   chmod +x run.sh
   nohup ./run.sh > server.log 2>&1 &
   ```
2. **Cai dat auto-start (Systemd)**:
   ```bash
   chmod +x run.sh install_service.sh
   sudo ./install_service.sh
   ```
   - Script se dang ky `chungkhoan.service` vao systemd va tu dong cho mang len truoc khi chay (`network-online.target`).
   - Xem log background bat cu luc nao: `sudo journalctl -u chungkhoan.service -f`

## Lich job

- ETL: 15:30 moi ngay (`ETL_HOUR`, `ETL_MINUTE`)
- Advice: 06:00 moi ngay (`ADVICE_HOUR`, `ADVICE_MINUTE`)

Ban co the chay tay:

- `POST /api/jobs/run-etl`
- `POST /api/jobs/run-advice`

## Cac endpoint chinh

- `GET /api/health`
- `GET/PUT /api/portfolio/template`
- `GET/PUT /api/portfolio/watchlist-config`
- `GET/PUT /api/portfolio/holdings-config`
- `GET /api/portfolio/health`
- `GET /api/alerts`
- `GET /api/advice/latest`
- `GET /api/advice/history`
- `GET /api/market/{symbol}/snapshot`
- `GET /api/market/watchlist-snapshots`
- `GET /api/market/{symbol}/history?days=5`

## Rule theo tung ma

- `Ngung tich san` va `chot loi` ho tro theo **tung ma** thong qua `symbol_rules`.
- Tren UI da co form ro rang theo cot (Ma, Ngung tich san, Chot loi), khong can nhap theo chuoi nen kho hieu.
- UI template da bo truong Email va Ho ten de thao tac nhanh theo che do 1 user local.
- Da bo rule ky luat chung tren UI; he thong chi nhan rule rieng theo tung ma.
- Ty le giai ngan (`ratio`) duoc tinh tren **tong tai san** = tien mat + gia tri co phieu, khong tinh tren tung ma rieng le.

## Kiem thu nhanh (smoke test)

Da co script test web + API workflow:

```bash
cd backend
conda run -n kyluat-dautu python smoke_test.py
```

Script se test:

- tai trang web `/`
- health API
- luu template danh muc
- chay ETL
- lay snapshot ma co phieu
- chay advice
- doc advice moi nhat
- doc alerts
- doc portfolio health

Luu y: smoke test dung DB rieng `backend/data/smoke_test.db`, khong ghi de du lieu thuc te cua ban.

Neu thanh cong, se in: `SMOKE_TEST_PASS: Web + API workflow OK`

## Debug huong dan nhanh

1. Kiem tra `backend/logs/error.log` truoc.
2. Lay `X-Request-ID` tu response header de tra nguoc log.
3. Neu AI khong chay:
   - kiem tra quota (`ai_usage_logs`)
   - kiem tra `GEMINI_ENABLED`, `GEMINI_CMD` trong `.env`
   - xem dong `ai_skipped` trong `app.log`.
4. Neu du lieu trong ngay chua co: chay `POST /api/jobs/run-etl`.

## Ghi chu

- Du lieu thu thap tu `vnstock_data` neu co cai; neu khong co se dung fallback deterministic de app van hoat dong.
- Da bo fallback du lieu fake. He thong chi dung du lieu that tu `vnstock_data`.
- Neu chua co `vnstock_data`, ETL se bao loi nguon du lieu thieu thay vi tao du lieu gia lap.
- Gia mua/ban la goi y dinh luong, nguoi dung ra quyet dinh cuoi.
