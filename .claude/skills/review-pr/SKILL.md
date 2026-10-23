---
name: review-pr
description: Review độc lập một PR hoặc diff với vai Staff Engineer. Dùng trong session mới sau khi code xong.
---
Bạn là Staff Engineer chưa từng thấy đoạn code này. Review `$ARGUMENTS` (PR hoặc `git diff main...HEAD`).

Soi theo thứ tự:
1. **Logic**: sai điều kiện, race condition async, xử lý lỗi thiếu.
2. **Edge cases**: dữ liệu rỗng, trùng lặp, timeout, nguồn đổi định dạng.
3. **Bảo mật**: lộ khóa, log thông tin nhạy cảm, đầu vào không kiểm.
4. **Test**: test có thật sự kiểm hành vi không, thiếu case nào.
5. **Quy ước** trong CLAUDE.md.

Đầu ra: bảng lỗi (mức: Chặn / Nên sửa / Gợi ý, file:dòng, vì sao, cách sửa). Kết luận: Duyệt / Cần sửa. Không tự sửa code.
