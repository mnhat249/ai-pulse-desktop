---
name: prepare-release
description: Chuẩn bị phát hành phiên bản mới: kiểm tra, cập nhật changelog, đề xuất số phiên bản. Không tự deploy.
---
1. Chạy `python scripts/check.py`; phải đạt hoàn toàn.
2. Chạy `/audit-security`.
3. Cập nhật `CHANGELOG.md` từ `git log` kể từ tag gần nhất (Thêm / Sửa / Thay đổi).
4. Đề xuất số phiên bản (semver) và lý do.
5. Liệt kê các bước phát hành cần người thật duyệt.

**Dừng ở đây.** Tag, push, tạo release phải chờ tôi xác nhận.
