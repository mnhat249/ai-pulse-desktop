# NeuralRadar — Kế hoạch triển khai

Ngày 23/10/2026 · Tu Hoang Anh · Dự án cá nhân, repo public

NeuralRadar là app Windows chạy ngầm, tự gom tin AI, lọc trùng, lọc rác và tóm tắt bằng tiếng Việt. App chỉ dành cho 1 người dùng và chi phí 0 đồng. Kế hoạch chia thành 6 giai đoạn, mỗi giai đoạn có "cổng" kiểm tra; có MVP dùng thật sau giai đoạn 3.

---

## Tiến độ (cập nhật 24/10/2026)

Chú giải: `[x]` xong và đã kiểm (test/chạy thật) · `[~]` code đã viết nhưng chưa kiểm hoặc chưa đủ · `[ ]` chưa làm · *(cần bạn)* việc chỉ người thật làm được. Chi tiết bàn giao: `HANDOFF.md`.

| Giai đoạn | Trạng thái | Cổng | Ghi chú |
| --- | --- | --- | --- |
| 0. Nền móng | Xong code | Đạt | `pytest` xanh; test 10 task ghi 1.000 dòng + 1 kết nối đọc không còn "database is locked". Còn việc ngoài code *(cần bạn)* |
| 1. Nguồn API đầu tiên | Xong code | Chưa đạt | Chạy thật 4 nguồn lưu 370 bài, lần 2 không trùng. Chưa chạy 24 giờ liên tục *(cần bạn)* |
| 2. Xử lý tin | Xong code | Chưa đạt | Chuẩn hóa URL, gán cụm 2 tầng, lọc rác luật, tóm tắt LLM theo lô, quota, xếp hạng, công cụ `export-pairs` / đo F1 / đo rác đều có test. Thiếu dữ liệu thật: gán nhãn tay, khóa Gemini/Groq, model fastembed chưa tải *(cần bạn)* |
| 3. Giao diện (MVP) | Xong code | Chưa đạt | Widget, tray, toast, đã đọc/bookmark, bộ lọc, tình trạng nguồn, chỉ một bản, thoát sạch. Chưa dùng thật 3 ngày *(cần bạn)* |
| 4. Thêm nguồn | Chưa bắt đầu | — | — |
| 5. Hoàn thiện | Chưa bắt đầu | — | — |

Code MVP (giai đoạn 0–3) đã xong; `python scripts/check.py` xanh với 280 test. Chưa commit: toàn bộ thay đổi đang nằm trong worktree `mvp` (nhánh `worktree-mvp`); hook pre-commit đang bị chặn vì Python msys thiếu ruff.

---

## 1. Mục tiêu và phạm vi

Mục tiêu: mỗi ngày mở widget là đọc được tối đa 30 tin AI đã lọc sạch, bằng tiếng Việt, mỗi sự kiện chỉ hiện 1 lần, không cần mở hàng chục tab.

| MVP (giai đoạn 0–3) | Sau MVP (giai đoạn 4–5 và lâu dài) | Không làm |
| --- | --- | --- |
| Nguồn GitHub, HuggingFace (paper + model), Hacker News | RSS blog các lab AI, AINews (tóm tắt X), Bluesky, Reddit OAuth, ArXiv theo từ khóa | Facebook |
| Lọc trùng 2 tầng (theo ID, theo nghĩa) | Đóng gói thành file .exe, tự khởi động cùng Windows | macOS, Linux |
| Lọc rác (luật + LLM) | Xếp hạng theo sở thích, tóm tắt tuần | Nhiều người dùng, bộ cài cho người khác |
| Tóm tắt 3 ý tiếng Việt | Hỏi đáp trên kho tin đã lưu | Module X bằng trình duyệt (trừ khi đo thấy cần) |
| Widget nổi, icon khay, toast, đã đọc, bookmark | | Bất kỳ thứ gì tốn tiền |

### Chỉ số thành công của MVP

- Tối đa 30 cụm tin mỗi ngày.
- Tối đa 10% tin rác lọt qua.
- Không sự kiện nào hiện 2 lần.
- Không link nào do LLM tự viết ra.
- Chạy 7 ngày liền không crash.
- Chi phí: 0 đồng.

Giả định về nhịp làm: khoảng 10 giờ mỗi tuần. Số tuần trong kế hoạch chỉ để ước lượng, không phải hạn chót.

---

## 2. Stack kỹ thuật đã chốt

Stack bám sát SRS, chỉ đổi 2 chỗ: thêm Alembic để nâng cấp DB không mất dữ liệu (vì app dùng lâu dài), và dùng fastembed thay vì PyTorch để file đóng gói không quá nặng.

| Phần | Chọn | Lý do |
| --- | --- | --- |
| Ngôn ngữ, môi trường | Python 3.12, `uv` | uv cài nhanh, khóa phiên bản thư viện bằng `uv.lock` |
| Gọi mạng | `httpx` (async) + `tenacity` | tenacity lo việc thử lại có giãn cách |
| RSS | `feedparser` | Đọc được gần như mọi loại feed |
| Lịch chạy | `APScheduler` 3.x (`AsyncIOScheduler`), ghim `<4` | Bản 4.x đổi API, tài liệu trên mạng chủ yếu là 3.x |
| Cơ sở dữ liệu | SQLite + SQLAlchemy 2.0 async + `aiosqlite`, `Alembic` | Alembic giúp đổi cấu trúc bảng mà không phải xóa DB |
| Mô hình dữ liệu, cài đặt | `pydantic` v2, `pydantic-settings` | Kiểm tra dữ liệu từ API và từ LLM |
| Lưu API key | `keyring` | Key nằm trong Windows Credential Manager, không nằm trong file |
| Lọc trùng theo nghĩa | `fastembed` + model `paraphrase-multilingual-MiniLM-L12-v2` | Chạy ONNX, nhẹ hơn PyTorch rất nhiều, hiểu cả tiếng Anh lẫn tiếng Việt |
| Mốc so sánh | `scikit-learn` (TF-IDF) | Để chứng minh embedding tốt hơn bằng số liệu |
| LLM | `google-genai` (Gemini Flash / Flash-Lite, free tier), `groq` dự phòng | Tên model để trong file cài đặt, đổi không cần sửa code |
| Giao diện | `customtkinter`, `pystray` + `Pillow`, `winotify` | Đúng lựa chọn đã chốt, chỉ cần Windows |
| Log | `logging` + `RotatingFileHandler` | Có sẵn trong Python |
| Test, lint | `pytest`, `pytest-asyncio`, `respx`, `ruff`, `pre-commit`, `gitleaks` | respx giả lập API để test không cần mạng; gitleaks chặn lộ key |
| Đóng gói | `PyInstaller` (dạng thư mục) | Dạng thư mục khởi động nhanh hơn dạng 1 file |

---

## 3. Kiến trúc và hợp đồng dữ liệu

App có 2 luồng và đúng 1 chỗ ghi DB. Scraper không bao giờ chạm vào giao diện, và giao diện không bao giờ gọi mạng.

```text
┌─ LUỒNG NỀN (asyncio + scheduler) ──────────────────────────────────┐
│  Adapters: mỗi nguồn 1 task, nguồn nào lỗi chỉ ghi log nguồn đó     │
│  MVP: GitHub · HuggingFace · Hacker News                            │
│  Sau MVP: RSS blog · AINews · Bluesky · Reddit (OAuth) · module X   │
│                           │ RawItem                                 │
│                           ▼                                         │
│  1. Chuẩn hóa → 2. Lọc trùng → 3. Lọc rác → 4. Tóm tắt (gộp 5–10)  │
│                           │                                         │
│                           ▼                                         │
│  Task ghi DB: chỉ có 1  ──►  SQLite (bật WAL)                       │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ queue.Queue: báo "có tin mới"
                            ▼
┌─ LUỒNG CHÍNH (giao diện) ───────────────────────────────────────────┐
│  Widget nổi (CustomTkinter) · Icon khay (pystray) · Toast (winotify)│
│  Tự đọc DB bằng kết nối riêng                                       │
└─────────────────────────────────────────────────────────────────────┘
```

Các phần nói chuyện với nhau qua 3 "hợp đồng" dưới đây. Giữ ổn định 3 thứ này thì thay ruột từng phần thoải mái.

**1. Adapter:** mọi nguồn đều có cùng hình dạng.

```python
class SourceAdapter(Protocol):
    name: str  # "github", "hf_papers", ...
    interval_minutes: int  # chu kỳ quét

    async def fetch(self, client: httpx.AsyncClient) -> list[RawItem]:
        """Lỗi thì ném SourceError, không bao giờ làm sập app."""
```

**2. RawItem:** 1 bài thô từ 1 nguồn.

```python
class RawItem(BaseModel):
    source: str  # tên adapter
    source_id: str  # ID gốc, cùng source để chống ghi trùng
    url: str
    title: str
    text: str = ""
    author: str | None = None
    published_at: datetime
    metrics: dict[str, float] = {}  # sao, điểm HN, trendingScore...
    links: list[str] = []  # link trích từ nội dung, dùng để lọc trùng
```

**3. Digest:** thứ LLM được phép trả về. Cố ý không có trường link.

```python
class Digest(BaseModel):
    cluster_id: int
    title_vi: str  # tiêu đề tiếng Việt, ngắn
    innovation: str  # ý 1: cái gì mới
    impact: str  # ý 2: dùng để làm gì
    importance: int  # 1–5
    is_noise: bool
    noise_reason: str | None = None


# Ý 3 (link) do app lấy từ cụm: repo, paper hoặc URL gốc.
```

Một vòng xử lý: lấy tin → ghi `raw_items` → chuẩn hóa → gán vào cụm → lọc rác bằng luật → gọi LLM theo lô → ghi `clusters` → báo giao diện.

### Lọc trùng 3 tầng

1. **Trùng ID:** cùng repo GitHub, cùng mã ArXiv, cùng model HF, hoặc cùng URL sau khi bỏ tham số theo dõi (`utm_...`). Gộp ngay, không tốn gì. Tầng này bắt được phần lớn tin trùng vì bài Reddit, HN, X thường dán link repo hoặc paper.
2. **Trùng nghĩa:** tạo embedding cho tiêu đề + đoạn đầu (model đa ngôn ngữ chạy máy). Chỉ so với các cụm trong 72 giờ gần nhất.
3. **Chọn ngưỡng bằng dữ liệu:** gom 150–200 cặp bài thật, tự gán "cùng tin / khác tin", thử nhiều ngưỡng, lấy ngưỡng có F1 cao nhất. Giữ TF-IDF làm mốc để so.

### Mô hình dữ liệu (7 bảng)

| Bảng | Giữ gì | Vì sao cần |
| --- | --- | --- |
| `raw_items` | nguồn, ID gốc, URL gốc + URL đã chuẩn hóa, tiêu đề, nội dung, tác giả, giờ đăng, giờ lấy | Khóa duy nhất (nguồn, ID gốc) nên quét lại không bị ghi trùng |
| `metric_snapshots` | mã mục, loại chỉ số (sao, trendingScore), giá trị, thời điểm | Tính tốc độ sao/24h |
| `clusters` | lần thấy đầu/cuối, điểm quan trọng, có phải rác không, tóm tắt 3 ý (JSON), link chính | 1 cụm = 1 sự kiện; widget hiện theo cụm |
| `cluster_items` | cụm nào gồm những bài nào | Hiện "xuất hiện ở 3 nguồn" và các link gốc |
| `user_state` | đã đọc lúc nào, có bookmark không | Tách riêng để xóa tin cũ không mất bookmark |
| `source_runs` | nguồn, giờ chạy, thành công/lỗi, số tin | Màn hình "tình trạng nguồn" |
| `llm_usage` | ngày, nhà cung cấp, số lần gọi | Chặn vượt quota |

### Cấu trúc thư mục

```text
ai-pulse-desktop/
  app/
    main.py          # UI ở luồng chính, khởi động luồng nền
    config.py        # cài đặt; API key đọc từ keyring
    core/models.py   # RawItem, Cluster, Digest
    adapters/        # base.py, github.py, huggingface.py, hackernews.py,
                     # rss.py, reddit.py, bluesky.py
    pipeline/        # normalize.py, dedup.py, noise.py, digest.py
    storage/         # db.py, writer.py, queries.py
    scheduler.py
    ui/              # widget.py, tray.py, notifier.py
  tests/fixtures/
  CLAUDE.md  HANDOFF.md  .env.example  .gitignore
```

---

## 4. Lộ trình tổng

Tổng cộng khoảng 8 tuần ở nhịp 10 giờ/tuần, có MVP sau khoảng 6 tuần. Nguồn dễ và ổn định làm trước; giao diện làm sau phần xử lý vì widget chỉ đáng dùng khi tin bên trong đã sạch. Mỗi giai đoạn có 1 "cổng": chưa đạt thì chưa sang giai đoạn sau.

| Giai đoạn | Thời gian | Nội dung chính | Xong khi (cổng) |
| --- | --- | --- | --- |
| 0. Nền móng | ~1 tuần | Repo, CLAUDE.md, pre-commit; RawItem, Cluster, Digest; SQLite + Alembic + task ghi; keyring. Gửi đơn xin Reddit Data API ngay. | pytest xanh; 10 task ghi + 1 kết nối đọc không bị lỗi khóa DB |
| 1. Nguồn API đầu tiên | ~1 tuần | GitHub (kèm snapshot sao), HuggingFace, Hacker News; fixture; scheduler; source_runs. Chạy liên tục để gom dữ liệu. | Chạy 24 giờ; rút mạng rồi cắm lại vẫn tự hồi phục |
| 2. Xử lý tin | ~2 tuần | Chuẩn hóa URL; lọc trùng 2 tầng; gán nhãn 150–200 cặp; lọc rác; tóm tắt theo lô. Gemini → Groq → tiêu đề gốc; đếm quota. | Ngưỡng chọn bằng F1; tối đa 10% rác; 3 ngày không cụm nào lặp |
| 3. Giao diện (MVP) | ~2 tuần | 2 luồng; widget nổi; icon khay; toast; đã đọc, bookmark; chỉ 1 bản; tình trạng nguồn. Dùng hằng ngày, ghi vào feedback.md. | **MVP:** dùng thật 3 ngày liền, không cần mở trình duyệt để lướt tin |
| 4. Thêm nguồn | ~1 tuần | RSS blog lab AI; AINews (tóm tắt X hằng ngày); Bluesky; Reddit (nếu được duyệt). Bắt đầu sổ x-missed.md. | Thêm nguồn mà không phải sửa pipeline hay giao diện |
| 5. Hoàn thiện | ~1 tuần | PyInstaller; tự khởi động cùng Windows; dọn dữ liệu, sao lưu; màn hình cài đặt; README. Xem x-missed.md rồi quyết có làm module X riêng. | Cài và chạy được trên 1 máy Windows sạch |

---

## 5. Giai đoạn 0 — Nền móng (khoảng 1 tuần)

Kết quả: một bộ khung chạy được, có test và có DB, nhưng chưa lấy tin. Làm kỹ phần này thì các giai đoạn sau chỉ còn là "thêm file".

### Thiết lập repo

- [x] Tạo `pyproject.toml` bằng `uv`, thêm `ruff`, `pytest`, `pytest-asyncio` — *có `pyproject.toml`; máy chưa có `uv` nên dùng `.venv` + pip, vẫn dùng được với `uv sync`*
- [x] `.gitignore` gồm: `.env`, `*.db`, `*.db-wal`, `*.db-shm`, `local_plugins/`, `storageState*.json`, `dist/`, `build/`, `logs/`
- [~] `pre-commit` chạy `ruff` và `gitleaks` mỗi lần commit — *có `.pre-commit-config.yaml`; chưa `pre-commit install`, chưa chạy thử (cần bạn)*
- [x] Viết `CLAUDE.md` (mục tiêu, lệnh chạy, lệnh test, luật cứng) và `HANDOFF.md` rỗng
- [x] Tạo cây thư mục: `app/core`, `app/adapters`, `app/pipeline`, `app/storage`, `app/ui`, `tests/fixtures`

### Lõi

- [x] `core/models.py`: `RawItem`, `Cluster`, `Digest` bằng pydantic
- [x] `config.py`: đọc `%APPDATA%\NeuralRadar\settings.toml`; key đọc từ `keyring`
- [x] Lệnh `python -m app.setkey gemini` (và `groq`, `github`) để lưu key vào keyring
- [x] Logging ra `%APPDATA%\NeuralRadar\logs\`, xoay vòng 5 file × 2 MB

### Cơ sở dữ liệu

- [x] `storage/db.py`: tạo engine, bật `journal_mode=WAL`, `busy_timeout=5000`
- [x] Migration Alembic đầu tiên cho 7 bảng: `raw_items`, `metric_snapshots`, `clusters`, `cluster_items`, `user_state`, `source_runs`, `llm_usage` — *giai đoạn 2 thêm migration 0002 (`item_keys`, `item_embeddings`, cột `noise_reason`)*
- [x] `storage/writer.py`: 1 task duy nhất lấy lệnh ghi từ `asyncio.Queue` và ghi theo lô

### Việc ngoài code (làm ngay vì phải chờ)

- [ ] Gửi đơn xin Reddit Data API (dùng cá nhân, phi thương mại) *(cần bạn)*
- [ ] Tạo GitHub token loại fine-grained, chỉ quyền đọc repo public, có hạn dùng *(cần bạn; lưu bằng `python -m app.setkey github`)*
- [ ] Tạo Gemini API key trong AI Studio và Groq API key *(cần bạn; lưu bằng `python -m app.setkey gemini` / `groq`)*

> **Cổng:** `pytest` xanh. Một test cho 10 task cùng ghi 1.000 dòng trong khi 1 kết nối khác đọc liên tục, không có lỗi "database is locked".
>
> **Trạng thái: đạt** (test `test_ten_writers_and_a_reader_never_hit_database_locked`, chạy lặp 8 lần không lỗi; `check.py` 88 test xanh trước khi thêm giai đoạn 2).

---

## 6. Giai đoạn 1 — Nguồn API đầu tiên (khoảng 1 tuần)

Kết quả: lấy tin thật từ 3 nguồn ổn định nhất, chạy ngầm theo lịch, in ra màn hình bằng dòng lệnh. Chưa có giao diện, chưa có LLM. Dữ liệu gom trong giai đoạn này sẽ dùng để gán nhãn ở giai đoạn 2, nên cho nó chạy liên tục càng sớm càng tốt.

### Khung adapter

- [x] `adapters/base.py`: giao diện `SourceAdapter`, lỗi `SourceError(source, reason)`
- [x] Mỗi lần gọi có timeout 20 giây, thử lại tối đa 3 lần (giãn cách 1s, 4s, 16s); lỗi 429 thì đợi đúng `Retry-After` — *chờ quá 60s thì bỏ lượt (`RateLimited`)*
- [x] Test chung cho mọi adapter: trả về `list[RawItem]` đúng định dạng; mạng lỗi thì ném `SourceError`, không làm sập app

### Từng nguồn

- [x] **GitHub:** tìm repo theo 5 topic (`llm`, `ai-agent`, `computer-vision`, `mcp`, `rag`) có push trong 48 giờ, cộng repo mới tạo trong 7 ngày, sắp theo sao. Dùng `ETag` để lần gọi không đổi trả 304, không tốn quota
- [x] **GitHub:** lưu snapshot số sao mỗi lần quét; tính tốc độ sao/24h; repo chưa đủ 24h thì dùng sao chia tuổi repo
- [x] **HuggingFace:** `/api/daily_papers` và `/api/models?sort=trendingScore&direction=-1&limit=50`; lưu snapshot `trendingScore`
- [x] **Hacker News:** Algolia HN Search API, chỉ lấy story, lọc theo từ khóa AI và điểm tối thiểu (ví dụ từ 50 điểm)
- [x] Gọi API thật 1 lần, lưu vào `tests/fixtures/` cho từng nguồn; test parser đọc fixture (dùng `respx`)

### Chạy

- [x] `scheduler.py`: mỗi nguồn là 1 job riêng, chu kỳ 15–30 phút
- [x] Ghi bảng `source_runs` sau mỗi lần chạy (giờ, thành công/lỗi, số tin)
- [x] Lệnh `python -m app.cli run-once` (chạy 1 vòng) và `python -m app.cli serve` (chạy ngầm, in tin mới) — *`serve` chưa có test tự động, chưa chạy dài*

> **Cổng:** chạy liên tục 24 giờ. Rút mạng giữa chừng rồi cắm lại, app tự hồi phục. 1 nguồn lỗi không làm dừng 2 nguồn còn lại.
>
> **Trạng thái: chưa đạt.** Đã kiểm: chạy thật `run-once` 4 nguồn (370 bài, lần 2 không trùng) và test mô phỏng nguồn lỗi/hồi phục/tạm ngưng. Còn thiếu: chạy `python -m app.cli serve` liên tục 24 giờ và rút mạng thử *(cần bạn)*.

---

## 7. Giai đoạn 2 — Xử lý tin (khoảng 2 tuần)

Kết quả: tin thô biến thành các cụm sự kiện sạch, có điểm quan trọng và tóm tắt 3 ý tiếng Việt. Đây là phần quyết định app có "đáng đọc" hay không, nên mọi ngưỡng đều chọn bằng dữ liệu thật.

### Chuẩn hóa và lọc trùng

- [x] `pipeline/normalize.py`: chuẩn URL (bỏ `utm_*`, bỏ `#...`, thống nhất `github.com/owner/repo`, mã ArXiv, mã model HF); trích mọi link có trong nội dung bài — *có test (31 test cùng noise/ranking đạt)*
- [x] Lọc trùng tầng 1: bài có cùng khóa chuẩn (repo, ArXiv, model, URL) thì gộp vào cụm có sẵn — *`pipeline/cluster.py`, có test (gộp 2 cụm khi có bài bắc cầu và giữ bookmark; chạy thật 370 bài không có khóa nào nằm ở 2 cụm)*
- [x] Xuất 150–200 cặp bài "có thể trùng" từ dữ liệu đã gom ra file CSV; tự gán nhãn "cùng tin / khác tin" *(gán nhãn: cần bạn)* — *lệnh `python -m app.cli export-pairs`, có test; cần embedding đã lưu trong DB, tức đã chạy app một lần với model thật*
- [x] Script `scripts/eval_dedup.py`: so TF-IDF với embedding, thử ngưỡng từ 0.50 đến 0.95, chọn ngưỡng có F1 cao nhất; ghi kết quả vào `docs/dedup-eval.md` — *`app/quality/dedup.py` (lối tắt `scripts/eval_dedup.py`), có test với embedder giả; chưa chạy trên dữ liệu thật vì chưa có nhãn*
- [~] Lọc trùng tầng 2: embedding bằng fastembed, chỉ so với các cụm trong 72 giờ gần nhất; lưu vector vào DB để không tính lại — *logic gán cụm đã test với embedder giả (cửa sổ 72 giờ, ngưỡng lấy từ cài đặt, embedder lỗi thì quay về tầng 1); ngưỡng 0.80 là tạm, chưa chọn bằng F1; model fastembed thật chưa tải/chạy lần nào*

### Lọc rác

- [x] Tầng luật: từ khóa quảng cáo/khóa học/giveaway, ngưỡng tối thiểu theo nguồn (điểm HN, số sao) — *`pipeline/noise.py`, có test*
- [ ] Gán nhãn tay 50 tin "rác / không rác" để đo bộ lọc *(cần bạn)*; script `app/quality/noise.py` (lối tắt `scripts/eval_noise.py`) đã có và có test, chạy khi có nhãn

### Tóm tắt bằng LLM

- [x] `pipeline/digest.py`: gộp 5–10 cụm vào 1 lần gọi; 1 lần gọi trả cả điểm rác lẫn tóm tắt — *có test với LLM giả (lô, trần quota, dự phòng, sai schema); client Gemini/Groq thật chưa gọi lần nào (cần key)*
- [x] Bắt trả JSON đúng schema `Digest`, kiểm bằng pydantic; sai schema thì thử lại 1 lần, vẫn sai thì bỏ qua lần đó
- [x] Schema không có trường link; link chính lấy từ cụm (repo, paper hoặc URL gốc) — *`Digest` có validator chặn link trong văn bản; `primary_url` lấy từ bài gốc*
- [x] Prompt ngắn, tiếng Việt đơn giản; lưu prompt trong file riêng để chỉnh không cần sửa code — *`app/pipeline/prompts/digest_vi.txt`*
- [x] Bảng `llm_usage` đếm số lần gọi mỗi ngày; đặt trần thấp hơn mức free tier; hết trần thì cụm chờ hôm sau — *trần mặc định 100 lần/ngày mỗi nhà cung cấp*
- [x] Thứ tự dự phòng: Gemini → Groq → chỉ hiện tiêu đề gốc

### Xếp hạng

- [x] Điểm quan trọng = kết hợp tốc độ sao/trending, số nguồn trong cụm, điểm LLM. Trọng số để trong file cài đặt — *`pipeline/ranking.py`, có test*

> **Cổng:** ngưỡng lọc trùng được chọn bằng dữ liệu và có ghi lại F1. Tối đa 10% rác lọt trên tập 50 tin. Chạy 3 ngày không có cụm nào lặp. Không lần nào vượt trần quota.
>
> **Trạng thái: chưa đạt, phần code đã xong.** Còn thiếu đều cần dữ liệu thật: gán nhãn 150–200 cặp rồi chạy `app/quality/dedup.py` để chọn ngưỡng bằng F1; gán nhãn 50 tin rồi chạy `app/quality/noise.py` (mục tiêu ≤ 10% rác lọt); chạy 3 ngày không cụm lặp; cần khóa Gemini/Groq để tóm tắt thật. Đã kiểm bằng test: không khóa chuẩn nào nằm ở 2 cụm; không vượt trần quota; văn bản tóm tắt không chứa link.

---

## 8. Giai đoạn 3 — Giao diện, ra MVP (khoảng 2 tuần)

Kết quả: app chạy ngầm thật sự, đọc tin trên widget, có icon khay và thông báo. Hết giai đoạn này là bắt đầu dùng hằng ngày.

> **Trạng thái: xong code, chưa đạt cổng MVP.** Chạy `python -m app.main`. Đã kiểm: 48 test giao diện/luồng nền (widget Tk thật, tray qua hàng đợi, khởi động lại luồng nền, chỉ một bản, thoát sạch) và một lần chạy thật ~70 giây (3 nguồn thật, vòng xử lý, thoát bằng lệnh `quit`, mã thoát 0). Giao diện (thiết kế theo skill `frontend-design`: dải tín hiệu theo điểm, chip nguồn) đã chụp từ cửa sổ thật và chỉnh theo ảnh. Chưa kiểm: toast Windows và icon khay thật, chạy nhiều ngày. Cổng MVP cần bạn dùng 3 ngày liền *(cần bạn)*.

### Hai luồng

- [x] `main.py`: luồng chính chạy CustomTkinter; 1 luồng nền chạy vòng lặp asyncio + scheduler + task ghi
- [x] Luồng nền báo "có tin mới" qua `queue.Queue`; widget kiểm tra hàng đợi bằng `after(500, ...)` rồi tự đọc DB
- [x] Luật cứng: không gọi mạng, không chờ I/O trong luồng giao diện
- [x] Luồng nền gặp lỗi thì ghi log và tự khởi động lại; giao diện không chết theo

### Widget

- [x] Cửa sổ nổi bán trong suốt, kéo thả được, nhớ vị trí và kích thước; tùy chọn luôn nằm trên cùng
- [x] Danh sách cụm xếp theo điểm; bấm vào để xem 3 ý; mỗi cụm có nút mở link, bookmark, đánh dấu đã đọc
- [x] Hiện số nguồn trong cụm (ví dụ "GitHub · HN · HF")
- [x] Bộ lọc: chưa đọc, bookmark, theo nguồn
- [x] Màn hình "tình trạng nguồn" đọc từ `source_runs`: lần chạy cuối, lỗi gần nhất

### Khay hệ thống và thông báo

- [x] Icon khay (`pystray.run_detached()`): hiện/ẩn widget, chạy ngay, tạm dừng, thoát
- [x] Toast (`winotify`) khi cụm có điểm cao hoặc xuất hiện ở 3 nguồn trở lên; tối đa vài toast mỗi giờ
- [x] Chỉ chạy 1 bản: mở lần 2 thì đưa widget của bản đang chạy lên
- [x] Thoát sạch: dừng scheduler, chờ task ghi xong, đóng DB

### Dùng thử

- [ ] Dùng hằng ngày; ghi tin rác lọt và tin bị sót vào `docs/feedback.md`
- [ ] Sửa luật lọc rác và trọng số xếp hạng theo sổ ghi

> **Cổng MVP:** dùng 3 ngày liền mà không cần mở trình duyệt để lướt tin AI. Giao diện không bao giờ bị đơ khi đang lấy tin.

---

## 9. Giai đoạn 4 — Thêm nguồn (khoảng 1 tuần)

Kết quả: phủ thêm tin từ blog, X (gián tiếp), Bluesky và Reddit. Đây cũng là bài kiểm tra kiến trúc: thêm nguồn mà không phải đụng vào pipeline hay giao diện.

- [ ] `adapters/rss.py` dùng chung cho mọi feed; danh sách feed để trong file cài đặt
- [ ] Thêm feed: blog các lab AI, HF blog, AINews (`news.smol.ai/rss.xml`), blog/Substack cá nhân của những người bạn theo dõi trên X
- [ ] `adapters/bluesky.py`: `getAuthorFeed` trên `public.api.bsky.app` cho danh sách handle
- [ ] `adapters/reddit.py` qua OAuth (nếu đơn đã được duyệt): `r/LocalLLaMA`, `r/MachineLearning`
- [ ] (Tùy chọn) ArXiv API theo từ khóa riêng của bạn
- [ ] Bắt đầu sổ `docs/x-missed.md`: 2 tuần, ghi mỗi tin quan trọng thấy trên X mà app không có

> **Cổng:** mỗi nguồn mới chỉ cần 1 file adapter + 1 fixture + 1 dòng cài đặt. Không sửa file nào trong `pipeline/` hay `ui/`.

---

## 10. Giai đoạn 5 — Hoàn thiện (khoảng 1 tuần)

Kết quả: app tự chạy khi bật máy, tự dọn dữ liệu, không cần mở terminal nữa.

- [ ] Đóng gói bằng PyInstaller (dạng thư mục, không hiện cửa sổ console, có icon)
- [ ] Model embedding tải về lần chạy đầu, lưu ở `%APPDATA%`, không nhét vào file đóng gói
- [ ] Tự khởi động cùng Windows: tạo shortcut trong thư mục Startup; bật/tắt trong cài đặt
- [ ] Dọn dữ liệu: xóa cụm cũ hơn 30 ngày (trừ bookmark), `VACUUM` mỗi tuần, giữ 7 bản sao lưu DB
- [ ] Màn hình cài đặt đơn giản: chu kỳ quét, ngưỡng toast, bật/tắt từng nguồn
- [ ] README: cài đặt, lưu key, kiến trúc, cách thêm nguồn mới
- [ ] Xem sổ `x-missed.md`: quyết định có làm module X riêng hay không

> **Cổng:** cài và chạy được trên 1 máy Windows sạch. Có thể thử bằng Windows Sandbox có sẵn trong Windows Pro.

---

## 11. Đo chất lượng và kiểm thử

Mọi chỉ số dưới đây đều đo được bằng script hoặc truy vấn DB, không dựa vào cảm giác.

| Chỉ số | Cách đo | Mục tiêu |
| --- | --- | --- |
| Số cụm mỗi ngày | Đếm trong `clusters` | Tối đa 30 |
| Tin rác lọt | Tập 50 tin gán nhãn + sổ `feedback.md` | Tối đa 10% |
| Sự kiện bị lặp | Test tìm 2 cụm cùng khóa chuẩn trong 72 giờ | 0 |
| Link bịa | Test: link của mỗi tóm tắt phải nằm trong các bài gốc của cụm | 0 |
| Lọc trùng | F1 trên tập 150–200 cặp | Cao hơn TF-IDF, ghi trong `dedup-eval.md` |
| Độ ổn định | Chạy liên tục | 7 ngày không crash |
| Chi phí | Hóa đơn | 0 đồng |

### Các loại test

- **Parser:** đọc fixture, không gọi mạng.
- **Hợp đồng adapter:** 1 test chung chạy cho mọi adapter.
- **DB đồng thời:** nhiều task ghi + 1 kết nối đọc.
- **LLM:** dùng câu trả lời LLM đã ghi sẵn để test việc kiểm schema và việc lấy link.
- **Đánh giá:** `eval_dedup.py` và `eval_noise.py` chạy lại mỗi khi đổi ngưỡng hoặc model.

---

## 12. Vận hành và xử lý lỗi

Nguyên tắc: một phần hỏng thì chỉ phần đó dừng, app vẫn hiện được tin đã có.

| Tình huống | App làm gì |
| --- | --- |
| Mạng chập chờn | Thử lại 3 lần có giãn cách; vẫn lỗi thì ghi `source_runs` và đợi chu kỳ sau |
| API trả 429 | Đợi đúng thời gian `Retry-After` |
| 1 nguồn lỗi 3 lần liền | Tạm ngưng nguồn đó 2 giờ; màn hình tình trạng nguồn hiện cảnh báo |
| API đổi định dạng | Parser ném lỗi rõ tên nguồn; các nguồn khác chạy bình thường |
| Hết quota LLM | Cụm chuyển sang "chờ tóm tắt", widget hiện tiêu đề gốc |
| Luồng nền crash | Ghi log, khởi động lại vòng lặp; giao diện vẫn chạy |
| Đổi cấu trúc DB | Chạy migration Alembic khi khởi động; sao lưu DB trước khi migrate |

Dữ liệu và log đều nằm ở `%APPDATA%\NeuralRadar\`: `neuralradar.db`, `backups/`, `logs/`, `settings.toml`, `models/`.

---

## 13. Bảo mật cho repo public

Repo public thì mọi thứ từng commit đều có thể bị người khác đọc, kể cả khi đã xóa ở commit sau. Vì vậy phải chặn từ đầu.

- API key chỉ nằm trong `keyring`. File `.env.example` chỉ có tên biến, không có giá trị thật.
- `gitleaks` chạy trong pre-commit để chặn commit có key.
- Trước lần push đầu tiên: chạy `gitleaks detect` trên toàn bộ lịch sử git.
- DB, log, model, phiên đăng nhập đều nằm ở `%APPDATA%`, không nằm trong thư mục repo.
- `local_plugins/` nằm trong `.gitignore`. Module X bằng trình duyệt (nếu làm) để ở đây.
- GitHub token loại fine-grained, chỉ quyền đọc, có ngày hết hạn.
- Không gửi dữ liệu riêng tư cho LLM: free tier của Gemini có thể dùng nội dung gửi lên để huấn luyện model.

---

## 14. Rủi ro và phương án dự phòng

Rủi ro lớn nhất với dự án cá nhân làm lâu dài không phải kỹ thuật, mà là bỏ dở giữa chừng. Kế hoạch giảm rủi ro này bằng cách có bản dùng thật sớm.

| Rủi ro | Dấu hiệu | Dự phòng |
| --- | --- | --- |
| API đổi định dạng | Nguồn trả 0 tin, test fixture vẫn xanh | Lưu fixture mới, sửa 1 file adapter |
| Hết quota Gemini | Lỗi 429 | Groq dự phòng, gộp nhiều cụm hơn mỗi lần gọi, xếp hàng chờ |
| Reddit không duyệt đơn | Không có key | AINews và Hacker News đã phủ phần lớn tin Reddit |
| X sót nhiều tin | Sổ `x-missed.md` dài | Làm module X riêng (ngoài repo) hoặc trả phí X API |
| Ngưỡng lọc trùng sai dần | Cụm lặp hoặc gộp nhầm | Gán nhãn thêm, chạy lại `eval_dedup.py` mỗi 2 tháng |
| Giao diện bị đơ | Widget không phản hồi | Kiểm lại luật 2 luồng; không có I/O trong luồng giao diện |
| Bỏ dở giữa chừng | Lâu không commit | MVP sớm; mỗi giai đoạn đều tự dùng được; HANDOFF.md giúp quay lại nhanh |

---

## 15. Quy trình làm việc với Claude mỗi giai đoạn

Mỗi giai đoạn đi theo cùng 1 vòng, để Claude luôn có đủ ngữ cảnh và bạn luôn kiểm soát được kết quả.

1. **Lên kế hoạch:** đưa Claude mục giai đoạn trong tài liệu này + `HANDOFF.md`; nhờ chia thành các việc nhỏ, mỗi việc 1 commit.
2. **Tách nhánh:** mỗi adapter hoặc mỗi phần lớn là 1 nhánh/worktree riêng; các adapter làm song song được.
3. **Viết test trước:** fixture và test hợp đồng có trước, code sau.
4. **Review độc lập:** cuối giai đoạn, 1 subagent chưa thấy quá trình viết code đọc diff và đối chiếu với "Cổng" của giai đoạn.
5. **Ghi bàn giao:** cập nhật `HANDOFF.md` (xong gì, dở gì, bước tiếp) và tick checklist trong tài liệu này.

---

## 16. Sau MVP: hướng phát triển lâu dài

Mỗi hướng là 1 giai đoạn nhỏ có cổng riêng; chọn theo nhu cầu thật sau khi đã dùng app vài tuần.

- **Xếp hạng theo sở thích:** dùng tin bạn bookmark và tin bạn mở để đẩy chủ đề hay đọc lên trên.
- **Tóm tắt tuần:** 1 trang gom các sự kiện lớn nhất tuần, xuất được ra Markdown.
- **Hỏi đáp trên kho tin đã lưu:** ví dụ "tuần trước có model OCR nào mới?", dùng lại embedding đã có.
- **Thêm nguồn bằng file cài đặt:** RSS và Bluesky thêm bằng 1 dòng, không cần sửa code.
- **Module X riêng:** chỉ khi sổ `x-missed.md` cho thấy đáng làm.
