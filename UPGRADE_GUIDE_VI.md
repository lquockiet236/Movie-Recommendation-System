# Hướng dẫn bản nâng cấp Guest / User / Admin

## Cài đặt trên Windows (PowerShell)
Yêu cầu Python 3.12 trở lên (Django 6.0.4).

```powershell
cd movie-recommendation-system
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Nếu máy chỉ có Python 3.13, thay `py -3.12` bằng `py -3.13`.

Mở http://127.0.0.1:8000/ để xem website. Trang quản trị: http://127.0.0.1:8000/admin/.

- Khách vãng lai: tìm kiếm và xem gợi ý mà không cần đăng nhập.
- Người dùng: đăng ký `/accounts/signup/`, đăng nhập `/accounts/login/`, lưu/bỏ yêu thích, xem/xóa lịch sử.
- Admin: tạo bằng `createsuperuser`, đăng nhập `/admin/`, quản lý phim và tài khoản bằng Django Admin.
- Dữ liệu gợi ý mẫu nằm ở `demo_model/`; cấu hình `MODEL_DIR=demo_model` trong `.env` để dùng dữ liệu mẫu (nếu chưa có thư mục `models/`).

**Lưu ý:** `Movie` trong SQLite và danh mục của mô hình gợi ý (Parquet) là hai nguồn dữ liệu khác nhau. Thêm phim qua `/admin/` chỉ cập nhật SQLite; chưa đưa phim mới vào mô hình gợi ý. Phim yêu thích được lưu bằng tên phim của kết quả gợi ý. Lịch sử chỉ ghi nhận tìm kiếm thành công khi đã đăng nhập. Gợi ý cá nhân hóa từ yêu thích/lịch sử chưa được triển khai.

**Dữ liệu cũ:** ZIP nâng cấp không đóng gói `db.sqlite3` để tránh phát tán dữ liệu tài khoản. Nếu cần giữ phim và tài khoản cũ, sao chép file `db.sqlite3` từ dự án cũ sang thư mục gốc của bản nâng cấp *trước khi chạy migrate* và sao lưu trước khi thay thế.

**Triển khai thật:** thiết lập `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, HTTPS và database bền vững trước khi đưa lên Internet.
