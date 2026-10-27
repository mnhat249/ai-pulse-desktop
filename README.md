# NeuralRadar

App Windows chạy ngầm, tự gom tin AI từ nhiều nguồn, lọc trùng, lọc rác và tóm tắt bằng tiếng Việt. Một người dùng, chi phí 0 đồng.

- Kế hoạch và tiến độ: [`docs/PLAN.md`](docs/PLAN.md)
- Bàn giao, việc còn lại: [`HANDOFF.md`](HANDOFF.md)
- Sổ ghi chép khi dùng thật: [`docs/feedback.md`](docs/feedback.md), [`docs/x-missed.md`](docs/x-missed.md)

## Cài đặt
Cần Python 3.11 trở lên trên Windows.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Muốn đúng phiên bản thư viện đã kiểm (như CI và bản đóng gói): `pip install -r requirements-dev.lock` rồi `pip install -e . --no-deps`.

## Lưu khóa API
Khóa chỉ nằm trong Windows Credential Manager (không nằm trong file hay biến môi trường):

```bash
python -m app.setkey gemini   # tóm tắt tiếng Việt (Gemini Flash, free tier)
python -m app.setkey groq     # dự phòng khi Gemini hết quota
python -m app.setkey github   # tùy chọn: token chỉ đọc, tránh bị giới hạn 403
```
Không có khóa Gemini/Groq thì app vẫn chạy: tin hiện bằng tiêu đề gốc, kèm nhãn "Chờ tóm tắt".

## Chạy
```bash
python -m app.main            # widget nổi + icon khay + toast, chạy ngầm
```
Lần chạy đầu tải model embedding (khoảng 500 MB) về thư mục dữ liệu để lọc trùng theo nghĩa; không có model thì app vẫn lọc trùng theo link, repo, mã paper.

Bấm X trên widget chỉ ẩn vào khay; chuột phải icon khay để "Chạy ngay", "Tạm dừng" hoặc "Thoát". Mở lần hai sẽ đưa widget đang chạy lên thay vì chạy bản thứ hai.

Đọc tin:
- Tab **Tin tức**: mỗi trang 6 tin (`[ui] page_size`, tối đa `max_clusters_shown` tin), nút "‹ Trước / Sau ›". Mỗi thẻ có tiêu đề đầy đủ, tiêu đề gốc, đoạn giới thiệu (do LLM viết; tin cũ hoặc chưa tóm tắt thì là đoạn đầu bài gốc), chip nguồn, chip chủ đề và chip thuật ngữ. Bấm thẻ để xem "Cái mới", "Dùng để" và từng bài nguồn.
- Hàng chủ đề: "★ Của tôi" (hợp các chủ đề trong `[topics] enabled`), "Mọi chủ đề", "Model mới", "Dùng Claude" (skill, plugin, subagent, MCP, CLAUDE.md...), "Ảnh/video AI". Từ khóa sửa được trong `[topics.rules.<khóa>]`.
- Tab **Thuật ngữ**: hơn 100 từ viết tắt AI/CS (RAG, MoE, LoRA, MCP...) giải thích bằng tiếng Việt, tìm được không cần gõ dấu. Bấm chip thuật ngữ trên thẻ tin để mở đúng mục đó. Dữ liệu ở `app/glossary/terms_vi.toml`.

Dòng lệnh, không giao diện:
```bash
python -m app.cli run-once    # quét một vòng rồi xử lý
python -m app.cli serve       # chạy ngầm theo lịch, in tin mới
python -m app.cli status      # tình trạng từng nguồn
python -m app.cli maintain    # dọn dữ liệu cũ, sao lưu, VACUUM ngay
```

## Dữ liệu và cài đặt
Mọi thứ nằm ở `%APPDATA%\NeuralRadar\`: `neuralradar.db`, `settings.toml`, `logs\`, `backups\`, `models\`. Nếu Python của bạn là bản Microsoft Store thì thư mục này bị ảo hóa vào `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation...\LocalCache\Roaming\NeuralRadar`.

Bấm "Cài đặt" trên widget để bật/tắt từng nguồn, đổi chu kỳ quét, ngưỡng toast và bật tự khởi động cùng Windows (thay đổi áp dụng khi mở lại app). Mọi thứ khác sửa trực tiếp trong `settings.toml`, ví dụ thêm một feed RSS:

```toml
[[rss]]
name = "Blog riêng"
url = "https://blog.example/feed.xml"
interval_minutes = 60
```
Chú ý: khi khai báo `[[rss]]` thì danh sách này thay hẳn danh sách mặc định. Lần bấm "Lưu" đầu tiên trong màn hình Cài đặt cũng ghi cả danh sách feed hiện tại vào `settings.toml`, nên feed mặc định thêm ở bản sau sẽ không tự xuất hiện (xóa mục `[[rss]]` khỏi file để dùng lại danh sách mặc định). Feed sai (không phải http/https hoặc trùng tên) bị bỏ và ghi vào log; `settings.toml` hỏng thì được đổi tên thành `settings.toml.bad` và app dùng cài đặt mặc định.

Dữ liệu tự dọn (chạy sau khi mở app 2 phút rồi mỗi 24 giờ): cụm không có bài mới trong 30 ngày bị xóa (trừ cụm có bookmark), app nhớ các bài đã xóa 180 ngày để feed trả lại bài cũ không thành "tin mới"; mỗi tuần sao lưu DB (giữ 7 bản) và chạy VACUUM.

## Nguồn tin
GitHub (repo AI mới nổi), HuggingFace (papers, models), Hacker News, RSS (AINews, HF blog, OpenAI, DeepMind, Google AI), Bluesky (vài tài khoản AI). Reddit chưa làm vì cần đơn Reddit Data API được duyệt.

## Kiến trúc
Hai luồng: luồng nền (asyncio + APScheduler) thu thập, lọc trùng, lọc rác, tóm tắt và là nơi **duy nhất** ghi DB; luồng giao diện (CustomTkinter) chỉ đọc DB bằng kết nối riêng, không gọi mạng. Chi tiết và sơ đồ ở mục 3 của [`docs/PLAN.md`](docs/PLAN.md).

```
app/adapters/   mỗi nguồn một file (SourceAdapter -> list[RawItem])
app/core/       RawItem, Cluster, Digest; sources.py (thông tin trình bày/xếp hạng từng nguồn)
app/pipeline/   chuẩn hóa URL, gán cụm, lọc rác, tóm tắt LLM, xếp hạng
app/storage/    SQLite + Alembic, Writer (nơi ghi DB duy nhất)
app/ui/         widget, khay, toast, cài đặt
app/quality/    công cụ đo ngưỡng lọc trùng và tỉ lệ rác lọt
```

## Thêm một nguồn mới
Chỉ cần: một file adapter trong `app/adapters/`, một dòng import trong `app/adapters/__init__.py`, một dòng trong `build_adapters` (`app/scheduler.py`), một mục trong cài đặt (`app/config.py`).

1. Adapter có `name`, `interval_minutes`, `warnings` và `async fetch(client) -> list[RawItem]`; gọi mạng qua `request()` (timeout, thử lại, `Retry-After`), lỗi thì ném `SourceError`.
2. Trong file adapter, `register(SourceInfo(...))` (nhãn, màu, thứ tự chọn link chính, chỉ số "độ nóng") ở `app/core/sources.py`.
3. Ngưỡng lọc rác và thang độ nóng: thêm một mục vào `noise.thresholds` và `ranking.heat_scales` trong cài đặt.
4. Lưu một phản hồi thật vào `tests/fixtures/` và thêm một dòng vào `CASES` của `tests/test_adapters.py` (test hợp đồng chung).
Không cần sửa `pipeline/` hay `ui/`; một test tự động (`test_pipeline_and_ui_contain_no_per_source_code`) giữ điều này.

## Phát triển
```bash
python scripts/check.py        # format, lint, mypy, pytest, quét khóa (như trước khi commit)
python scripts/build_exe.py    # đóng gói dist/NeuralRadar/NeuralRadar.exe (PyInstaller, dạng thư mục)
```
MCP GitHub (`.mcp.json`, chế độ chỉ đọc) cần biến `GITHUB_TOKEN` có quyền đọc.

Chạy bằng Python trong `.venv`. Đóng gói chưa được thử trên máy Windows sạch (nên thử bằng Windows Sandbox).
