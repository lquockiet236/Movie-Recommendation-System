# Giai đoạn 2 — TMDB và cá nhân hóa

## Chức năng
- Guest: khám phá phim, xem chi tiết, không lưu tương tác.
- User: lưu/bỏ yêu thích bằng TMDB ID; đánh giá 1–5 sao; lịch sử tìm kiếm; lịch sử tương tác.
- Admin: quản lý trong Django Admin.
- Dữ liệu yêu thích cũ (theo tên phim) được giữ nguyên, chưa tự động ghép sang TMDB ID vì có thể trùng tên.

## Cập nhật trên máy Windows
1. Sao lưu `db.sqlite3` và `.env` từ dự án đang chạy. Không chia sẻ token.
2. Giải nén bản Phase2 sang thư mục mới, không ghi đè database cũ.
3. Chép `db.sqlite3` cũ vào thư mục mới cạnh `manage.py`.
4. Dùng môi trường `.venv` hiện có hoặc tạo lại: `py -3.12 -m venv .venv`; `.\.venv\Scripts\Activate.ps1`; `pip install -r requirements.txt`.
5. Thiết lập `TMDB_ACCESS_TOKEN` như giai đoạn 1 (hoặc khôi phục `.env` nếu dự án đang dùng).
6. Chạy `python manage.py migrate` rồi `python manage.py runserver`.
7. Mở `/movies/`, chọn phim, thử yêu thích và đánh giá; vào `/favorites/`, `/interactions/`, `/history/`.

## Lưu ý
- Chưa xây dựng thuật toán xếp hạng cá nhân hóa; đây là dữ liệu nền cho giai đoạn 3.
- Lượt mở chi tiết chỉ là tương tác, không được coi là người dùng đã xem phim.
- Dữ liệu TMDB cần Internet; cache giữ nguyên từ giai đoạn 1.
- Không bao gồm `.venv`, `.env`, hoặc `db.sqlite3` của máy bạn trong ZIP để tránh lộ bí mật và giảm dung lượng.
