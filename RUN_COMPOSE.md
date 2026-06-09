# Hướng dẫn khởi chạy hệ thống (Docker Compose) - Team Vision

Tài liệu này hướng dẫn cách chạy toàn bộ stack AI Vision Service bằng Docker Compose.

---

## 1. Chuẩn bị môi trường

- Cài đặt Docker Desktop hoặc Docker Engine.
- Cài đặt Node.js và npm.
- Khởi tạo network external (nếu chưa có):
  ```bash
  docker network create class-net
  ```

---

## 2. Thiết lập biến môi trường

Sao chép file `.env.example` thành `.env`:

```bash
cp .env.example .env
```

Kiểm tra và cấu hình lại `.env` nếu cần (VD: đổi port).

---

## 3. Khởi chạy toàn bộ hệ thống

Chạy lệnh Compose để build và khởi động Database, AI Service và API:

```bash
docker compose up -d --build
```

Kiểm tra trạng thái các container:

```bash
docker compose ps
docker compose logs -f
```

---

## 4. Kiểm tra thủ công (Readiness)

API của hệ thống sẽ chạy ở `http://localhost:8000`. Kiểm tra trạng thái:

```bash
curl http://localhost:8000/health
```bash
npm run test:compose
```

Report sinh tại:

```text
reports/newman-lab05-compose.xml
reports/newman-lab05-compose.html
```

---

## 5. Dừng stack

Khi không cần nữa, dừng và xoá các container bằng:

```bash
docker compose down
```

Nếu muốn xoá volume dữ liệu của DB, thêm tuỳ chọn `-v`:

```bash
docker compose down -v
```

---

## 6. Lệnh nhanh

Bạn có thể dùng Makefile:

```bash
make compose-up
make compose-down
make logs
```

---

## 7. Mẹo gỡ lỗi

- Sử dụng `docker compose ps` để xem trạng thái container.
- Nếu API trả lỗi kết nối DB, hãy kiểm tra biến môi trường `POSTGRES_*` trong `.env` và đảm bảo DB đã sẵn sàng (`pg_isready`).
- Nếu AI service cần tải mô hình lớn, tăng `start_period` của healthcheck trong `docker-compose.yml`.