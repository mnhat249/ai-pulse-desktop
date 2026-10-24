# NeuralRadar

App Windows chạy ngầm, tự gom tin AI, lọc trùng, lọc rác và tóm tắt bằng tiếng Việt.

- Kế hoạch triển khai và tiến độ: `docs/PLAN.md`
- Bàn giao, việc còn lại: `HANDOFF.md`
- Quy ước và lệnh: `CLAUDE.md`
- Quy trình làm việc với Claude: `docs/WORKFLOW.md`

## Chạy
```bash
pip install -e ".[dev]"
python -m app.setkey gemini   # lưu khóa vào Windows Credential Manager (cũng groq, github)
python -m app.main            # widget nổi + icon khay + toast, chạy ngầm
```
Không có khóa Gemini/Groq thì app vẫn chạy: tin hiện bằng tiêu đề gốc, chờ tóm tắt.
Lần chạy đầu sẽ tải model embedding (~200 MB) về `%APPDATA%\NeuralRadar\models`.

Chạy không giao diện (dòng lệnh):
```bash
python -m app.cli run-once   # quét 1 vòng rồi xử lý
python -m app.cli serve      # chạy ngầm theo lịch, in tin mới
python -m app.cli status     # tình trạng từng nguồn
```
Dữ liệu, log, cài đặt (`settings.toml`) nằm ở `%APPDATA%\NeuralRadar\`.
