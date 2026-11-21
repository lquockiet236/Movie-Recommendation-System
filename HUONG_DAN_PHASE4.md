# Giai đoạn 4 — Hybrid Recommendation

## Điểm mới
- `recommender/collaborative_filtering.py`: user-based collaborative filtering dựa trên đánh giá 1–5 sao và phim yêu thích (tương đương 4 sao nếu chưa đánh giá).
- Chỉ so sánh hai tài khoản khi có ít nhất 2 phim chung; độ tương đồng cosine trên điểm đánh giá trừ mốc trung lập 3, có shrinkage theo số phim chung.
- Chỉ gợi ý phim chưa tương tác và được người dùng tương tự đánh giá trên 3 sao.
- Với phim có bằng chứng CF: 65% điểm Content-Based + 35% CF; các phim khác giữ điểm Content-Based. Khi không đủ dữ liệu, hệ thống tự quay về giai đoạn 3.
- Lý do gợi ý được hiển thị trên `/for-you/`.

## Chạy trên Windows
1. Sao lưu `db.sqlite3` trước khi nâng cấp; giữ file database cũ ở cạnh `manage.py` trong bản mới.
2. Kích hoạt venv và cài `pip install -r requirements.txt`.
3. Cấu hình TMDB_ACCESS_TOKEN như giai đoạn 3.
4. `python manage.py migrate`
5. `python manage.py test recommender.tests_recommendation`
6. `python manage.py runserver` và mở `/for-you/`.

## Cách kiểm thử Hybrid
- Tạo User A và B; cả hai đánh giá cao cùng 2 phim (ví dụ 4–5 sao).
- User B đánh giá cao thêm phim C mà A chưa xem/đánh giá.
- Đăng nhập User A, mở `/for-you/`. Nếu TMDB trả về chi tiết phim C, phim này có thể xuất hiện với lý do “Người dùng có sở thích tương tự cũng đánh giá cao”.
- Thử User mới: hệ thống dùng phim phổ biến. Thử chỉ 1 phim đánh giá: hệ thống vẫn dùng Content-Based.
- Vì TMDB có thể thay đổi và còn nhiều ứng viên khác, phim C không nhất thiết đứng đầu.

## Lưu ý
- Đây là user-based collaborative filtering không phải huấn luyện neural network. Với ít người dùng hoặc ít phim chung, CF không có đủ bằng chứng; đây là hành vi dự kiến.
- Chưa có báo cáo Precision@K/Recall@K đáng tin cậy: cần tập dữ liệu đánh giá đủ lớn và tách train/test để tính các chỉ số này, không nên tự gán số liệu.
- Chưa thay đổi chức năng tìm kiếm gần đúng hoặc sửa chính tả; để giai đoạn tối ưu sau.
- Mô hình hiện lấy ma trận tương tác từ SQLite khi tạo gợi ý; nếu số lượng tài khoản lớn cần thêm cache hoặc giới hạn truy vấn.
