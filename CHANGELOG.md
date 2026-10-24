# Changelog
## [Unreleased]
- Thiết lập CLAUDE.md, hooks, commands, skills, subagents.
- Giai đoạn 0: gói `app/`, mô hình `RawItem`/`Cluster`/`Digest`, cài đặt + keyring, logging, SQLite WAL + Alembic, task ghi duy nhất.
- Giai đoạn 1: adapter GitHub, HuggingFace (papers, models), Hacker News; thử lại 1s/4s/16s; scheduler; `source_runs`; CLI `run-once`/`serve`/`status`.
- Giai đoạn 2: chuẩn hóa URL, gán cụm 2 tầng (khóa chuẩn + embedding), lọc rác theo luật, tóm tắt tiếng Việt theo lô (Gemini → Groq), trần quota, xếp hạng; công cụ `export-pairs`, đo F1 lọc trùng, đo rác lọt.
- Giai đoạn 3: widget nổi, icon khay, toast, đã đọc/bookmark, bộ lọc, tình trạng nguồn, chỉ một bản chạy, luồng nền tự khởi động lại, thoát sạch (`python -m app.main`).
- Giai đoạn 4: adapter RSS (mặc định AINews, HF blog, OpenAI, DeepMind, Google AI) và Bluesky; registry nguồn `app/core/sources.py` để thêm nguồn không sửa pipeline/ui; bật/tắt từng nguồn trong cài đặt.
- Giai đoạn 5: dọn dữ liệu (xóa cụm cũ trừ bookmark, sao lưu hằng tuần giữ 7 bản, VACUUM), tự khởi động cùng Windows, màn hình cài đặt, đóng gói PyInstaller (`scripts/build_exe.py`), README mới.
- Sửa: bấm "Chạy ngay" liên tiếp không còn chạy trùng một nguồn; bù embedding cho bài đã gom trước khi có model.
