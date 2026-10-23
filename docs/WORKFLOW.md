# Quy trình làm việc với Claude

## Mỗi task một worktree
```bash
git worktree add ../aipulse-<task> -b feat/<task>
cd ../aipulse-<task>
claude
```
Xong việc: merge qua PR, rồi `git worktree remove ../aipulse-<task>` (Claude sẽ hỏi trước khi xóa).

## Chia vai cho task lớn (mỗi vai một session riêng)
| Vai | Agent | Việc |
|---|---|---|
| A | researcher | Đọc code, lập kế hoạch |
| B | implementer | Viết code |
| C | tester | Chạy test, debug |
| D | reviewer | Review độc lập (session mới) |
| E | doc-updater | Docs + changelog |

## Review chéo
Sau khi xong, mở **session Claude mới**, chạy `/review-pr`. Session đó chưa thấy code lúc viết nên soi lỗi tốt hơn.

## Nghiệm thu
Không nhận "xong rồi". Phải có: file đã sửa, test đã chạy + kết quả, case chưa kiểm, log/screenshot.

## Bàn giao
Trước khi reset context: `/handoff` (Mục tiêu -> Quyết định -> File sửa -> Test -> Lỗi tồn đọng -> Bước tiếp).

## Biến môi trường cho MCP GitHub
Đặt `GITHUB_TOKEN` (quyền đọc là đủ; `.mcp.json` đã bật chế độ chỉ-đọc).
