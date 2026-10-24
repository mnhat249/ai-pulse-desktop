# HANDOFF

## Mục tiêu
Thực hiện `docs/PLAN.md`. Toàn bộ phần code của 6 giai đoạn (0–5) đã xong; còn các cổng cần dữ liệu thật, thời gian dùng thật và máy Windows sạch. Bảng "Tiến độ" đầu `docs/PLAN.md` là nguồn trạng thái chính.

## Nhánh và PR
- `worktree-mvp` (PR #1 vào `main`): giai đoạn 0–3.
- `feat/phase-4-5` (tách từ `worktree-mvp`): giai đoạn 4–5. Khi PR #1 được merge thì đổi base của PR mới sang `main`.
- `.claude/` và `CLAUDE.md` nằm trong `.gitignore` (không commit), chỉ có trên máy này.
- Hook commit của Claude chạy bản ở repo gốc nên không dùng được; commit bằng terminal của bạn, chạy `.\.venv\Scripts\python.exe scripts/check.py` trước.

## Quyết định chính
- Gói `app/`, `pyproject.toml`, SQLAlchemy 2 async + Alembic, APScheduler 3.x, tenacity, keyring, fastembed, google-genai/groq, customtkinter + pystray + winotify, feedparser, tomli-w, PyInstaller (dev).
- Python 3.11 trong `.venv` (kế hoạch ghi 3.12 và `uv`; máy này chưa có `uv`). Python của `.venv` là bản Microsoft Store nên thư mục dữ liệu bị ảo hóa (xem README).
- Chỉ `Writer` ghi DB; luồng giao diện chỉ đọc bằng kết nối riêng; callback tray chỉ đẩy lệnh vào queue.
- Gộp cụm: khóa chuẩn chỉ dùng URL chính + link do adapter cung cấp + (link trích từ nội dung nếu chỉ nhắc đúng một repo/paper); tầng embedding bỏ qua cụm đã là repo/paper khác; ngưỡng 0.80 là tạm.
- Hết quota hoặc lỗi LLM thì cụm "chờ tóm tắt" (widget hiện tiêu đề gốc), hoãn 60 phút.
- Registry nguồn `app/core/sources.py`: nhãn, màu, thứ tự chọn link chính, chỉ số "độ nóng" của từng nguồn; ngưỡng rác và thang độ nóng nằm trong cài đặt (`noise.thresholds`, `ranking.heat_scales`). Thêm nguồn không phải sửa `pipeline/` hay `ui/`.
- Link trong `RawItem.links` do adapter cung cấp được tin để gộp cụm, nên RSS chỉ đưa link bài viết vào đó (không đưa các link trong nội dung bản tin tổng hợp như AINews).
- `customtkinter` nhân kích thước cửa sổ theo DPI nhưng không nhân vị trí: khi lưu phải chia lại.
- Cài đặt từ giao diện ghi `settings.toml` rồi áp dụng khi mở lại app; tạo/xóa shortcut Startup chạy ở luồng riêng (PowerShell).

## Đã xong
- Giai đoạn 0–3: xem `docs/PLAN.md` (đã qua hai lượt review độc lập, đã sửa).
- Giai đoạn 4: `app/adapters/{rss,bluesky}.py`, registry nguồn, bật/tắt nguồn, fixture thật, sổ `docs/x-missed.md`.
- Giai đoạn 5: `app/maintenance.py` (xóa cụm cũ trừ bookmark, sao lưu hằng tuần giữ 7 bản, VACUUM), `app/startup.py`, `app/settings_store.py`, `app/ui/settings_{form,window}.py`, `scripts/build_exe.py` + `packaging/`, README mới, `docs/feedback.md`.
- Việc lặt vặt: chống chạy trùng một nguồn khi bấm "Chạy ngay" liên tiếp; bù embedding cho bài đã gom trước khi có model.
- `scripts/check.py` xanh (ruff, mypy, 390 test). `NeuralRadar.exe` chạy được ở thư mục dữ liệu tạm (migration, prompt, scheduler, RSS, Bluesky, vòng xử lý).

## Đã sửa theo review độc lập GĐ4-5
- Bài đã dọn không bị nạp lại thành "tin mới": bảng `seen_items` (migration 0003) giữ dấu vết (nguồn, id) 180 ngày; bài mồ côi được dọn độc lập và chia lô 500.
- Cài đặt Startup lưu lần hai (bật rồi tắt trong cùng một cửa sổ) và thử lại khi lần trước thất bại; `settings.toml` hỏng được báo trên cửa sổ; `_poll_startup` an toàn khi cửa sổ đã đóng.
- Feed RSS trùng tên (sau khi slug) hoặc URL không phải http/https bị bỏ và ghi log; `settings.toml` hỏng khi khởi động được đổi tên `.bad` và dùng mặc định.
- Ghi embedding bù lỗi không làm hỏng vòng xử lý; nháy đơn cong trong PowerShell được nhân đôi; `maintenance.json` ghi nguyên tử; bảo trì chạy sau 2 phút; ngày RSS ở tương lai bị kẹp về hiện tại.

## Chưa xong (cần người thật)
- Cổng GĐ1: chạy `python -m app.main` liên tục 24 giờ, rút mạng thử.
- Cổng GĐ2: gán nhãn 150–200 cặp (`python -m app.cli export-pairs`) rồi `python -m app.quality.dedup pairs.csv` để chọn ngưỡng; gán nhãn 50 tin rồi `python -m app.quality.noise`; lưu khóa Gemini/Groq (`python -m app.setkey gemini`); chạy 3 ngày không cụm lặp.
- Cổng MVP (GĐ3): dùng 3 ngày liền, ghi vào `docs/feedback.md`, chỉnh luật rác và trọng số.
- Cổng GĐ5: cài và chạy `dist/NeuralRadar/` trên máy Windows sạch (Windows Sandbox); lần chạy đầu tải model khoảng 500 MB.
- GĐ4: ghi `docs/x-missed.md` 2 tuần rồi quyết định module X; Reddit khi có đơn Reddit Data API được duyệt.
- Việc ngoài code: đơn Reddit, GitHub token fine-grained (`python -m app.setkey github`), `pre-commit install`, `gitleaks detect` trước lần push đầu; `.env.example` chưa tạo vì rule deny chặn ghi `.env.*`.
- Chưa kiểm bằng mắt: toast Windows, icon khay, màn hình "Nguồn" và "Cài đặt"; chưa thử DPI khác 125%.

## Còn tồn nhỏ
- Một phần tử hỏng trong phản hồi GitHub/HF/HN làm hỏng cả nguồn (RSS và Bluesky thì bỏ phần tử hỏng); `serve` (signal Windows) chưa có test tự động; trạng thái tạm ngưng nguồn chỉ nằm trong RAM; `metric_snapshots` chỉ được dọn khi cụm bị xóa; quota LLM tính theo ngày UTC; widget dựng lại toàn bộ thẻ mỗi lần làm mới.
- Anthropic chưa có RSS chính thức (404) nên chưa có trong danh sách feed mặc định.

## Bước tiếp
1. Commit giai đoạn 4–5 (terminal của bạn), review độc lập bằng `/review-pr` ở session mới, rồi PR.
2. Dùng thật vài ngày, ghi sổ, rồi chọn ngưỡng lọc trùng bằng dữ liệu.
