# HANDOFF

## Mục tiêu
Thực hiện `docs/PLAN.md`. Toàn bộ phần code của 6 giai đoạn (0–5) đã xong; còn các cổng cần dữ liệu thật, thời gian dùng thật và máy Windows sạch. Bảng "Tiến độ" đầu `docs/PLAN.md` là nguồn trạng thái chính.

## Nhánh và PR
- PR #1 (`worktree-mvp`, giai đoạn 0–3) và PR #2 (`feat/phase-4-5`, giai đoạn 4–5) đã merge vào `main`. Nhánh `worktree-mvp` có thể xóa.
- `feat/phase-4-5` có thêm 4 commit sau PR #2 (thang độ nóng, adapter bỏ phần tử hỏng, CI + `requirements-dev.lock`, sửa cửa sổ Cài đặt): chưa push, chờ PR #3.
- Bốn nhánh làm song song được cắt từ `main` (`f9e33a4`), **chưa có** 4 commit trên: `feat/metrics-doctor`, `worktree-restore-source-state`, `feat/quota-timezone`, `feat/widget-card-refresh`. Merge PR #3 trước, rồi rebase từng nhánh lên `main` (`feat/widget-card-refresh` dễ đụng `app/ui/widget.py`, vốn đã bị sửa ở `e0dd78c`).
- `.claude/` và `CLAUDE.md` nằm trong `.gitignore` (không commit), chỉ có trên máy này. Thư mục gốc đã khớp `origin/main`; `.claude/worktrees/` nằm trong `.git/info/exclude` để không bị `git add` nhầm.
- Hook commit (`.claude/hooks/pre_commit_guard.py`) chạy `scripts/check.py` của đúng worktree bằng `.venv` của nó; repo gốc đã có bản hook mới.

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

## Đã sửa ở lượt review lại GĐ4-5
- GitHub/HF/HN: phần tử hỏng bị bỏ và ghi vào `warnings` (như RSS/Bluesky), chỉ khi mọi phần tử đều hỏng mới ném `SourceError`.
- `metric_snapshots` được dọn cùng bảo trì: bỏ snapshot cũ hơn 7 ngày, luôn giữ snapshot mới nhất của mỗi chỉ số.

## Đã sửa sau lượt kiểm tra trên dữ liệu thật
- Thang độ nóng mặc định khớp phân bố thật (GitHub 500, HF paper 100): trước đó 41/495 cụm cùng điểm 57,1.
- Màn hình Tình trạng nguồn: tên dễ đọc (`sources.display_name`), cuộn được; cửa sổ Cài đặt hết dải trắng thừa.
- Chưa có khóa LLM thì mọi cụm "Chờ tóm tắt" và xếp hạng chỉ dựa vào độ nóng/số nguồn: cần `python -m app.setkey gemini`.

## Chưa xong (cần người thật)
- Cổng GĐ1: chạy `python -m app.main` liên tục 24 giờ, rút mạng thử.
- Cổng GĐ2: gán nhãn 150–200 cặp (`python -m app.cli export-pairs`) rồi `python -m app.quality.dedup pairs.csv` để chọn ngưỡng; gán nhãn 50 tin rồi `python -m app.quality.noise`; lưu khóa Gemini/Groq (`python -m app.setkey gemini`); chạy 3 ngày không cụm lặp.
- Cổng MVP (GĐ3): dùng 3 ngày liền, ghi vào `docs/feedback.md`, chỉnh luật rác và trọng số.
- Cổng GĐ5: cài và chạy `dist/NeuralRadar/` trên máy Windows sạch (Windows Sandbox); lần chạy đầu tải model khoảng 500 MB.
- GĐ4: ghi `docs/x-missed.md` 2 tuần rồi quyết định module X; Reddit khi có đơn Reddit Data API được duyệt.
- Việc ngoài code: đơn Reddit, GitHub token fine-grained (`python -m app.setkey github`), `pre-commit install`, `gitleaks detect` trước lần push đầu; `.env.example` chưa tạo vì rule deny chặn ghi `.env.*`.
- Chưa kiểm bằng mắt: toast Windows, icon khay, màn hình "Nguồn" và "Cài đặt"; chưa thử DPI khác 125%.

## Còn tồn nhỏ
- `serve` (signal Windows) chưa có test tự động; trạng thái tạm ngưng nguồn chỉ nằm trong RAM; quota LLM tính theo ngày UTC; widget dựng lại toàn bộ thẻ mỗi lần làm mới.
- Anthropic chưa có RSS chính thức (404) nên chưa có trong danh sách feed mặc định.

## Bước tiếp
1. Push `feat/phase-4-5`, mở PR #3 vào `main` (cần bạn duyệt); review bằng `/review-pr` ở session mới.
2. Sau khi PR #3 merge: rebase 4 nhánh làm song song lên `main`, mỗi nhánh một PR.
3. Lưu khóa (`python -m app.setkey gemini|groq|github`), chạy `python -m app.main` 24 giờ (lần đầu tải model khoảng 500 MB), rồi đo bằng `python -m app.cli metrics` khi nhánh `feat/metrics-doctor` đã vào.
4. Gán nhãn cặp và tin, chọn ngưỡng lọc trùng bằng F1, dùng thật 3 ngày, ghi sổ.
