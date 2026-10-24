# Sổ phản hồi khi dùng thật (feedback)

Dùng hằng ngày và ghi vào đây: tin rác lọt qua, tin quan trọng bị sót hoặc bị coi là rác, cụm bị gộp nhầm hoặc bị lặp. Cuối mỗi tuần, chỉnh luật lọc rác, ngưỡng lọc trùng và trọng số xếp hạng theo sổ này (xem `settings.toml`, mục `[noise]`, `[dedup]`, `[ranking]`).

## Chỉ số cần theo dõi (mục 11 của `docs/PLAN.md`)
- Số cụm mỗi ngày (tối đa 30 hiện trên widget).
- Tỉ lệ rác lọt (tối đa 10%): đếm trên 50 tin gần nhất, đo bằng `python -m app.quality.noise`.
- Sự kiện bị lặp (phải bằng 0).

## Tin rác lọt qua
| Ngày | Tiêu đề | Nguồn | Vì sao là rác | Cần chỉnh gì (từ khóa / ngưỡng) |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## Tin quan trọng bị sót hoặc bị coi là rác
| Ngày | Tiêu đề | Nguồn | Vì sao bị bỏ | Cần chỉnh gì |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## Cụm gộp nhầm hoặc bị lặp
| Ngày | Hai tin | Gộp nhầm hay lặp | Độ giống (nếu biết) |
| --- | --- | --- | --- |
|  |  |  |  |
