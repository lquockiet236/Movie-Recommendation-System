# Changelog

Tất cả thay đổi quan trọng của dự án Movie Recommendation System (CineRec)
được ghi trong file này.

## [Unreleased]

### Added
- Ứng dụng Django duyệt, tìm kiếm, xem chi tiết và lọc phim.
- Gợi ý tương tự dựa trên mô hình TF-IDF/SVD và top-K láng giềng được tính trước.
- Gợi ý cá nhân hóa kết hợp yêu thích, đánh giá, tương tác và collaborative filtering.
- Đăng ký, đăng nhập, đăng xuất, yêu thích, đánh giá và trang `For You`.
- Django Admin, dashboard quản trị và dashboard đánh giá mô hình.
- API `/api/search/`, `/api/model-status/` và `/api/health/`.
- Mô hình offline mẫu trong `demo_model/`.
- Tùy chọn thu thập dữ liệu TMDB và huấn luyện model mới.
- Cấu hình triển khai bằng Docker, Render và Gunicorn/Procfile.
- Trang lỗi 404/500 và autocomplete có hỗ trợ bàn phím.

### Changed
- Django 6 và Python 3.12 trở thành nền tảng phát triển/deploy chính.
- Runtime dependencies được tách khỏi dependencies huấn luyện trong
  `requirements-train.txt`.
- Serving ưu tiên top-K neighbours thay vì ma trận similarity đầy đủ.
- Dữ liệu TMDB dùng cho luồng trực tuyến; mô hình offline dùng cho suy luận.
- Model được nạp nền một lần trong mỗi process.
- Tìm tên phim theo thứ tự khớp chính xác, tiền tố, chuỗi con rồi fuzzy matching.
- Thư mục model được chọn theo `MODEL_DIR`, các thư mục `models_tmdb_*` mới nhất,
  `models/` rồi `demo_model/`.

### Fixed
- Áp dụng migration `recommender.0004_allow_same_title_tmdb_favorites` để đồng
  bộ ràng buộc giữa yêu thích TMDB và yêu thích legacy.
- Xử lý cột danh mục trong metadata Parquet dưới dạng NumPy array hoặc giá trị thiếu.
- Đọc cấu hình và ánh xạ title bằng UTF-8 để hỗ trợ tên phim Unicode.
- Dùng console logging thay cho file logging tới thư mục không tồn tại.
- Cấu hình proxy HTTPS và secure headers cho môi trường production.
- Health check báo trạng thái `starting`, `healthy`, `missing` hoặc `error`
  thay vì làm deploy thất bại ngay khi model còn đang tải.
- Poster và dữ liệu TMDB thiếu có fallback an toàn.

### Security
- `SECRET_KEY` bắt buộc khi chạy `DEBUG=False`.
- Hỗ trợ allow-list hostname, CSRF trusted origins, secure cookies và HSTS.
- TMDB Access Token được đọc từ biến môi trường, không commit vào mã nguồn.
- Inference runtime đọc JSON, Parquet và NumPy; không cần unpickle model serving.

### Documentation
- Cập nhật README với luồng cài đặt, chạy local, model và deployment.
- Bổ sung `CONTRIBUTING.md`, `SECURITY.md` và attribution cho dữ liệu TMDB.

## Nâng cấp database

Sau khi cập nhật mã nguồn, chạy migration và kiểm tra project:

```powershell
python manage.py migrate
python manage.py check
```

Sao lưu `db.sqlite3` trước khi nâng cấp nếu database chứa tài khoản, yêu thích
hoặc đánh giá cần bảo toàn.
