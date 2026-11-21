# Giai đoạn 1 — TMDB API

## Đã thực hiện
- Giữ nguyên website gợi ý dựa trên mô hình cũ tại `/` để không làm mất tính năng.
- Trang khám phá phim `/movies/`: phim phổ biến, thịnh hành, tìm kiếm tên, lọc thể loại/năm và phân trang.
- Trang chi tiết `/movies/<tmdb_id>/`: mô tả, poster, thể loại, điểm TMDB, phim tương tự.
- Khách vãng lai xem phim mà không cần tài khoản; người dùng đăng nhập được lưu lịch sử **tìm kiếm theo tên phim**.
- Django Admin cũ giữ nguyên tại `/admin/`.
- Dùng Django cache 15 phút (thể loại 24 giờ), timeout 10 giây, xử lý lỗi khi API không khả dụng.

## Cấu hình trên Windows (PowerShell)
Yêu cầu Python >=3.12 vì dự án gốc dùng Django 6.0.4.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:TMDB_ACCESS_TOKEN="DAN_TOKEN_READ_ACCESS_CUA_BAN_VAO_DAY"
$env:MODEL_DIR="demo_model"
python manage.py migrate
python manage.py runserver
```

Đăng ký TMDB và lấy **API Read Access Token** (chuỗi Bearer) từ phần API Settings của tài khoản TMDB. Không dùng chuỗi `api_key` thay cho Bearer token. Không đăng token lên GitHub, không gửi token vào chat và không đặt trong HTML/JS. Biến môi trường PowerShell chỉ tồn tại trong phiên terminal hiện tại. Để lưu cấu hình lâu dài, dùng cơ chế biến môi trường của máy hoặc hệ thống triển khai.

- Website: http://127.0.0.1:8000/
- Khám phá phim TMDB: http://127.0.0.1:8000/movies/
- Django Admin: http://127.0.0.1:8000/admin/

Nếu chưa có tài khoản quản trị: `python manage.py createsuperuser`.

## Giới hạn giai đoạn 1
- Trang gợi ý cũ vẫn dựa trên mô hình offline. Trang `/movies/` là luồng TMDB API mới, chưa phải hệ thống gợi ý cá nhân hóa.
- Yêu thích hiện tại vẫn lưu theo **tên phim** của mô hình cũ, chưa nối vào trang chi tiết TMDB.
- Django Admin vẫn quản lý bảng Movie nội bộ, chưa có nút nhập phim từ TMDB và chưa đồng bộ vào thuật toán gợi ý.
- Chưa xây dựng UserPreference, MovieInteraction, đánh giá phim hoặc xếp hạng hybrid.
- Chưa kiểm thử trực tiếp với TMDB API vì cần token của người dùng.

## Các bước tiếp theo
1. Chuyển FavoriteMovie sang tmdb_id, bổ sung nút yêu thích tại trang chi tiết, bảo toàn dữ liệu cũ.
2. Ghi nhận tương tác và đánh giá phim; xây dựng hồ sơ sở thích.
3. Lấy ứng viên phim qua TMDB, xây dựng và kiểm thử thuật toán hybrid.
4. Bổ sung thao tác nhập phim từ TMDB trong Django Admin và đo chất lượng gợi ý.

Ghi nguồn TMDB theo điều khoản của TMDB; cần kiểm tra yêu cầu logo/attribution khi công bố sản phẩm.
