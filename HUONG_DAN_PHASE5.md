# Giai đoạn 5 — Đánh giá thuật toán gợi ý

## Cách sử dụng

1. Sao lưu `db.sqlite3` từ bản đang chạy; giữ nguyên TMDB token ở cấu hình cục bộ, không chia sẻ token.
2. Giải nén ZIP mới. Chép `db.sqlite3` sang cạnh `manage.py` (nếu ZIP không chứa cơ sở dữ liệu).
3. Cài dependency từ `requirements.txt` trong virtual environment đang dùng.
4. `python manage.py migrate`
5. `python manage.py test recommender.tests_recommendation recommender.tests_evaluation`
6. `python manage.py runserver`
7. Đăng nhập tài khoản `is_staff=True` và mở `http://127.0.0.1:8000/evaluation/`.
8. Có thể chạy qua terminal: `python manage.py evaluate_recommendations --k 5`.

## Phương pháp và giới hạn

- **Leave-one-positive-out**: Với mỗi người dùng có >= 3 phim được đánh giá 4 hoặc 5 sao, giữ lại 1 phim có TMDB ID lớn nhất làm kiểm thử; dùng các đánh giá còn lại để tạo hồ sơ.
- Không sử dụng dữ liệu kiểm thử để huấn luyện; không thay đổi database.
- Tập ứng viên là các phim xuất hiện trong bảng MovieRating (trừ các phim đã đánh giá trong phần train). Không phải toàn bộ TMDB.
- **Collaborative Filtering**: sử dụng cùng hàm `collaborative_scores` như phiên bản 4, nhưng truyền dữ liệu train đã loại phim kiểm thử.
- **Content-Based (local)**: cosine TF-IDF từ các bản ghi `Movie` đã lưu SQLite; nếu thiếu metadata, thuật toán có thể không có ứng viên. Đây là phép thử ngoại tuyến, không phải phép đo của Content-Based trực tuyến.
- **Hybrid (local)**: xếp hạng trên hợp các ứng viên có điểm Content-Based hoặc CF với công thức 0.65×cosine + 0.35×CF. **Đây là phiên bản đại diện ngoại tuyến, không phải điểm Hybrid đầy đủ trên trang /for-you/**, vốn còn xét thể loại, chất lượng và tập ứng viên TMDB.
- Precision@K = số lượt dự đoán đúng / tổng số phim thực tế được gợi ý trong Top K trên các tài khoản đủ điều kiện.
- Recall@K = số phim kiểm thử xuất hiện trong Top K / tổng số phim kiểm thử (1 phim/người dùng). Trong thiết kế này Recall@K bằng HitRate@K.
- Coverage = tỷ lệ tài khoản đủ điều kiện có ít nhất một phim được gợi ý.
- Với dữ liệu quá ít, không có người dùng đủ điều kiện, các chỉ số hiển thị N/A thay vì 0.
- Không sử dụng số liệu này để khẳng định mô hình đã đạt chất lượng tốt trên người dùng thực tế; cần nhiều tài khoản và đánh giá hơn, và thêm kiểm thử với các phép chia train/test khác.

## Dữ liệu tối thiểu để thử

Tạo ít nhất 3 tài khoản; mỗi tài khoản đánh giá 4–5 sao cho >=3 phim; để CF có cơ hội hoạt động, cho hai tài khoản đánh giá trùng ít nhất 2 phim và có thêm phim riêng. Bảng `Movie` có metadata nếu đã lưu phim vào SQLite; nếu không, Content-Based (local) có thể không đánh giá được. Không tự động lấy metadata từ TMDB để tránh lỗi mạng hoặc gọi API hàng loạt.

## Những phần chưa thay đổi

- Trang tìm kiếm, sai chính tả, tên tiếng Việt và phim cũ để giai đoạn tối ưu sau.
- Không sửa công thức xếp hạng hay giao diện `/for-you/` của giai đoạn 4.
