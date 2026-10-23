---
name: audit-security
description: Kiểm tra bảo mật toàn repo (khóa API, phiên Playwright, dữ liệu cá nhân, phụ thuộc). Dùng trước khi phát hành.
---
Kiểm tra theo checklist:
1. Quét khóa/bí mật trong code và lịch sử git gần đây (`git log -p -S` các mẫu khóa phổ biến).
2. `.env`, `*.db`, `playwright/.auth/` có bị track không (`git ls-files`).
3. Log có in cookie, token, nội dung riêng tư không.
4. Phụ thuộc: chạy `pip list --outdated`, ghi chú gói có lỗ hổng đã biết.
5. Scraper: giới hạn tốc độ, không lưu dữ liệu cá nhân thừa.

Đầu ra: báo cáo Cao / Trung / Thấp kèm file và cách sửa. Không tự sửa; hỏi tôi trước.
