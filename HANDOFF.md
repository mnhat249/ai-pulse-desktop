# HANDOFF

## Mục tiêu
Thực hiện `docs/PLAN.md`. Phần code của MVP (giai đoạn 0–3) đã xong; còn các cổng cần dữ liệu thật và người dùng thật. Bảng "Tiến độ" đầu `docs/PLAN.md` là nguồn trạng thái chính.

## Quyết định
- Theo kế hoạch: gói `app/`, `pyproject.toml` (không còn `requirements*.txt`), SQLAlchemy 2 async + Alembic, pydantic, APScheduler 3.x, tenacity, keyring, fastembed, google-genai/groq, customtkinter + pystray + winotify.
- Python 3.11 trong `.venv` (kế hoạch ghi 3.12 và `uv`, máy này chưa có `uv`; `pyproject.toml` dùng được với `uv sync`).
- HuggingFace tách thành hai adapter `hf_papers` và `hf_models`.
- API đổi định dạng thì adapter ném `SourceError` rõ tên nguồn thay vì bỏ qua từng phần tử.
- Gộp cụm: khóa chuẩn chỉ dùng URL chính + link repo/paper/model (link chung chung như trang chủ không dùng để gộp); tầng 2 so embedding với cụm trong 72 giờ, ngưỡng mặc định 0.80 (tạm).
- Hết quota hoặc lỗi LLM thì cụm ở trạng thái "chờ tóm tắt" (widget hiện tiêu đề gốc), không lưu bản tóm tắt dự phòng.
- Luồng giao diện chỉ đọc DB bằng kết nối sqlite3 riêng (`query_only`); mọi ghi (đã đọc, bookmark) đi qua `Writer` của luồng nền. Callback của tray chỉ đẩy lệnh vào `queue.SimpleQueue`.
- Giao diện (`app/ui/theme.py`): nền sáng "hải đồ" `#E6ECE7`, chữ mực `#112A33`, dải tín hiệu bên trái mỗi thẻ cao theo điểm quan trọng (xanh biển → hổ phách → đỏ phao; đã đọc thì mờ), chip màu theo nguồn, Bahnschrift cho tiêu đề và Segoe UI cho nội dung. Tránh các kiểu rập khuôn trong skill `frontend-design` (nền kem + đất nung, nền đen + neon, chữ HOA, chuỗi `A · B · C`).
- `customtkinter` nhân kích thước cửa sổ theo DPI nhưng không nhân vị trí: khi lưu phải chia lại (`_get_window_scaling`), nếu không cửa sổ to thêm 25% mỗi lần mở.

## Đã xong
- Giai đoạn 0–1: xem `docs/PLAN.md`; đã sửa theo review độc lập (thử lại 1s/4s/16s, `RateLimited`, kết quả một phần ghi vào `source_runs`, sao lưu bằng `sqlite3.backup()`, tắt `serve` chờ job).
- Giai đoạn 2: `app/pipeline/{normalize,cluster,embeddings,noise,ranking,llm,digest,process,pairs}.py`, migration `0002`, prompt `prompts/digest_vi.txt`, `app/quality/{dedup,noise}.py` (lối tắt `scripts/eval_dedup.py`, `scripts/eval_noise.py`).
- Giai đoạn 3: `app/main.py`, `app/runtime.py`, `app/ui/{backend,widget,tray,notifier,model,state,single_instance}.py`, `app/storage/ui_queries.py`.
- `python scripts/check.py` xanh với 280 test. Đã chạy thật `python -m app.main` ~70 giây (embedder giả, mạng thật): quét 3 nguồn, vòng xử lý, thoát sạch mã 0, 370 bài → 347 cụm, 0 khóa chuẩn nằm ở 2 cụm.

## Đã sửa theo review độc lập GĐ2–3
- **Chặn:** toast không còn chèn được lệnh PowerShell/XML (`app/ui/notifier.py`: chỉ giữ chữ, số, vài dấu câu; URL chỉ nhận http(s) an toàn, `&` được escape). Có test với `$(...)`, backtick, `"@`, `]]>`.
- Gộp cụm: link trích từ nội dung chỉ dùng khi bài nhắc đúng một repo/paper/model; tầng embedding bỏ qua cụm đã là repo/paper khác (`strong_conflict`); gộp cụm giữ bookmark của cả hai bên, "đã đọc" chỉ giữ khi cả hai bên đã đọc.
- Lọc rác chỉ xét tiêu đề, dùng cụm từ rõ nghĩa ("online course", "discount code"...). Cờ rác và điểm của cụm trong cửa sổ 72 giờ được tính lại mỗi vòng, nên repo lên sao sẽ hết bị coi là rác và được báo lên giao diện.
- LLM: sai schema thì sang nhà cung cấp kế tiếp; cụm LLM không trả lời được bị hoãn 60 phút (không chặn hàng đợi, không đốt quota mỗi 5 phút); nội dung bài được escape `<` `>` `&` trong prompt.
- Giao diện: tạm dừng được áp lại sau khi luồng nền khởi động lại; đã đọc/bookmark phát sự kiện `state` (không bật toast); `single_instance` phân biệt "đã có bản chạy" với "cổng bị chương trình khác chiếm" (khi đó vẫn khởi động và log lỗi); toast đếm số nhóm nguồn (HF models + papers là một); `close_runtime` luôn đóng hết dù một bước lỗi.
- Chưa làm (mục nhỏ): quota theo ngày UTC, dựng lại toàn bộ thẻ mỗi lần làm mới.
- Lưu ý: chạy `run-once`/app nhiều lần liên tiếp không có token GitHub thì gặp 403 giới hạn tốc độ (app xử lý đúng, bỏ lượt); nên `python -m app.setkey github`.

## Chưa xong (cần người thật)
- Cổng giai đoạn 1: chạy `python -m app.cli serve` hoặc `python -m app.main` liên tục 24 giờ, rút mạng thử.
- Giai đoạn 2: chạy app một lần với model thật (tải ~200 MB về `%APPDATA%\NeuralRadar\models`), `python -m app.cli export-pairs`, gán nhãn cột `label`, chạy `python -m app.quality.dedup pairs.csv` để chọn ngưỡng và ghi `docs/dedup-eval.md`; gán nhãn 50 tin rồi chạy `python -m app.quality.noise`; lưu khóa Gemini/Groq (`python -m app.setkey gemini`).
- Cổng MVP: dùng 3 ngày liền, ghi tin rác lọt / tin sót vào `docs/feedback.md`, chỉnh luật rác và trọng số.
- Việc ngoài code của giai đoạn 0: đơn Reddit Data API, GitHub token fine-grained.
- `pre-commit install`; `gitleaks detect` trước lần push đầu; `.env.example` chưa tạo vì rule deny của dự án chặn ghi `.env.*`.
- Đã chụp và xem cửa sổ widget thật (3 cụm mẫu, thẻ thu gọn và mở rộng). Chưa kiểm bằng mắt: toast Windows, icon khay, màn hình "Nguồn"; giao diện chưa chạy trên máy có DPI khác 125%.
- Chưa commit: hook pre-commit chạy Python msys thiếu ruff nên chặn (cần đổi PATH hoặc sửa hook).

## Còn tồn từ review GĐ0–1
- Một phần tử hỏng làm hỏng cả nguồn; `serve` (signal Windows) chưa có test tự động; trạng thái tạm ngưng chỉ nằm trong RAM; `metric_snapshots` chưa có cách dọn (~60k hàng/ngày); `Settings` thiếu ràng buộc (`failure_pause_threshold=0`); keyring lỗi thì app crash lúc khởi động.

## Bước tiếp
1. Commit (sau khi xử lý hook), rồi cho chạy app vài ngày để gom dữ liệu thật.
2. Giai đoạn 4 (thêm nguồn) chỉ cần thêm adapter + fixture + cấu hình, không sửa `pipeline/` hay `ui/`.
