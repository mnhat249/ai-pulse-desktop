# AI Pulse Desktop (NeuralRadar)

## 1. Mục tiêu sản phẩm
App Desktop chạy ngầm: tự thu thập tin/repo AI từ GitHub, HuggingFace, ArXiv, Reddit, X, Facebook -> khử trùng lặp -> lọc rác -> tóm tắt 3 ý bằng tiếng Việt (Gemini) -> hiển thị bằng Floating Widget + System Tray + Toast.
Ưu tiên: đọc tin không tốn công, tín hiệu cao / nhiễu thấp, một nguồn lỗi không làm sập app.

Stack: Python 3.11+, AsyncIO, httpx, Playwright, SQLite, CustomTkinter.

## 2. Lệnh build / test / lint
| Việc | Lệnh |
|---|---|
| Cài môi trường dev | `pip install -r requirements.txt -r requirements-dev.txt` |
| Cài trình duyệt Playwright | `playwright install chromium` |
| Format | `ruff format .` |
| Lint | `ruff check .` |
| Typecheck | `mypy src` |
| Test | `pytest -q` |
| **Chạy tất cả (như trước commit)** | `python scripts/check.py` |
| Chạy app | `python -m aipulse` (khi đã có) |

## 3. Quy tắc code
- Type hints đầy đủ; I/O dùng `async/await`.
- Mỗi nguồn là một adapter trong `src/aipulse/ingestion/`, kế thừa lớp base, trả về cùng schema bài viết.
- Lỗi xử lý theo từng nguồn (timeout, retry, log). Không để một nguồn làm sập cả app.
- Dùng `logging`, không `print` trong code chính.
- Hàm nhỏ, một việc; không comment thừa. Giao diện và bản tóm tắt: **tiếng Việt**.
- Mỗi thay đổi hành vi phải có test.

## 4. Bảo mật
- Không bao giờ commit `.env`, khóa API, cookie/phiên đăng nhập Playwright (`playwright/.auth/`), file `.db`.
- Khóa API chỉ đọc từ biến môi trường (`.env.example` là mẫu).
- Scrape X/Facebook: tuân thủ giới hạn tốc độ, không lưu thông tin cá nhân người dùng ngoài những gì cần cho bản tóm tắt.
- Việc rủi ro cao (deploy, xóa dữ liệu, `git push`, merge PR, gửi tin/thông báo ra ngoài, tác vụ tiền): **phải hỏi và chờ người thật duyệt**.

## 5. Cách báo cáo khi xong việc (bắt buộc)
Không được chỉ nói "xong rồi". Báo cáo gồm:
1. Danh sách file đã sửa
2. Test/lint/typecheck đã chạy + kết quả thật (dán output rút gọn)
3. Case chưa kiểm tra
4. Log / screenshot / preview nếu có UI

## 6. Quy trình làm việc
- Việc lớn chia vai (xem `.claude/agents/`): researcher -> implementer -> tester -> reviewer -> doc-updater.
- Mỗi task một git worktree riêng (xem `docs/WORKFLOW.md`).
- Review cuối cùng làm ở **session Claude mới** (vai Staff Engineer), dùng skill `/review-pr`.
- Trước khi reset context hoặc đổi session, chạy `/handoff`.

## 7. Bài học (cập nhật ngay khi Claude làm sai)
> Mỗi khi Claude sai, thêm một dòng vào đây: ngày - lỗi - rule mới. Không sửa lỗi xong rồi bỏ đi.

- (chưa có)
