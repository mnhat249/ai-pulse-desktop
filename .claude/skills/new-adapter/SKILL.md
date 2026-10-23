---
name: new-adapter
description: Tạo scraper adapter mới cho một nguồn dữ liệu (GitHub, HuggingFace, Reddit, X, Facebook...) theo đúng chuẩn dự án. Dùng khi cần thêm nguồn tin mới.
---
# Tạo adapter mới cho: $ARGUMENTS

Các bước:
1. Đọc lớp base và một adapter có sẵn trong `src/aipulse/ingestion/` để theo đúng mẫu.
2. Chọn cách lấy dữ liệu: API chính thống (httpx + asyncio) ưu tiên; mạng xã hội đóng dùng Playwright + network intercept.
3. Tạo `src/aipulse/ingestion/<nguon>.py`: kế thừa base, async, trả về đúng schema bài viết, có timeout + retry + logging, bắt lỗi theo nguồn.
4. Tạo `tests/ingestion/test_<nguon>.py` với dữ liệu mẫu (mock, không gọi mạng thật).
5. Đăng ký adapter vào registry.
6. Chạy `python scripts/check.py`.

Đầu ra bắt buộc: danh sách file tạo/sửa, output của check.py, case chưa kiểm (ví dụ giới hạn tốc độ, đổi cấu trúc trang).
