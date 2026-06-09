# Readiness Checklist – Lab 05

Đây là danh sách kiểm tra (checklist) để đảm bảo stack Docker Compose của bạn đã sẵn sàng trước khi gửi bài. Hãy tick vào mỗi mục sau khi hoàn thành.

- [x] **1. Port Readiness:** Các cổng không bị xung đột, có thể dùng biến môi trường để thay đổi (`APP_PORT=8000`).
- [x] **2. DB Readiness:** PostgreSQL container chạy thành công, health check trả về ready (`pg_isready -U lab05`).
- [x] **3. Token / Secret Readiness:** Không hardcode token thật trong code; lấy từ biến môi trường `AUTH_TOKEN` (mặc định: `local-dev-token`).
- [x] **4. Network Readiness:** Tạo network `team-internal` cho giao tiếp nội bộ; API có thể gọi database qua hostname `db:5432` và AI qua `ai-service:9000`.
- [x] **5. AI Service Readiness:** Khởi tạo service AI thành công với health check trả về 200 OK.
- [x] **6. API / Version Readiness:** API trả về đúng version ở endpoint `/health` và báo cáo DB connected. Compose sử dụng tag rõ ràng cho image.hcr.io hoặc Docker Hub). Xác nhận rằng tag xuất hiện trong registry.

Ghi chú thêm những vấn đề gặp phải hoặc điều chỉnh tại đây:

```
- Mô tả…
```