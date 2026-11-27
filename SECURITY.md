# Chính sách bảo mật

## Phiên bản được hỗ trợ

Chỉ nhánh mặc định và phiên bản/deployment mới nhất của project được hỗ trợ vá
lỗi bảo mật. Fork hoặc bản local cũ không thuộc phạm vi bảo trì mặc định.

## Báo cáo lỗ hổng

Không mở issue công khai nếu báo cáo còn có thể trực tiếp hỗ trợ khai thác.
Ưu tiên private vulnerability report trong tab **Security** của repository.
Nếu repository chưa bật tính năng đó, liên hệ maintainer qua kênh riêng thay
vì đăng chi tiết trên issue công khai.

Báo cáo nên gồm:

- Mô tả lỗ hổng và tác động.
- URL, route hoặc file liên quan.
- Bước tái hiện.
- Commit hoặc phiên bản đang kiểm tra.
- Dữ liệu mẫu đã làm mờ secret.
- Đề xuất khắc phục nếu có.

Không cố trích xuất dữ liệu người dùng thật, làm gián đoạn dịch vụ hoặc truy cập
thêm tài nguyên ngoài phạm vi được phép.

## Cấu hình production bắt buộc

- Đặt `SECRET_KEY` dài, ngẫu nhiên và riêng cho môi trường triển khai.
- Đặt `DEBUG=False`.
- Cấu hình `ALLOWED_HOSTS` cho đúng domain.
- Cấu hình `CSRF_TRUSTED_ORIGINS` khi dùng form qua HTTPS.
- Không commit hoặc gửi `.env`, `db.sqlite3`, TMDB token hoặc log có secret.
- Chỉ chạy sau HTTPS hoặc proxy/TLS đã cấu hình.
- Chỉ nạp thư mục model và dữ liệu đã được kiểm tra.
- Sao lưu và phân quyền database nếu lưu dữ liệu người dùng thật.

Khi `DEBUG=False`, settings từ chối khởi động bằng development secret key.
Secure cookies, HSTS và SSL redirect được bật theo cấu hình mặc định.

## Bí mật và dữ liệu bên ngoài

- `TMDB_ACCESS_TOKEN` chỉ nên tồn tại trong environment variables.
- Nếu token bị commit hoặc gửi công khai, thu hồi và tạo token mới.
- Không đưa secret vào query string, log, template hoặc response JSON.
- SQLite phù hợp phát triển; cân nhắc database production khi triển khai quy mô
  lớn hoặc nhiều process ghi.

## Rủi ro mô hình

Đường dẫn inference runtime đọc JSON, Parquet và NumPy array; không dùng
`pickle.load` để tải mô hình thường trực.

File `.pkl` trong quá trình huấn luyện là Python pickle. Chỉ mở file pickle từ
nguồn đáng tin cậy và không tải file pickle không xác định trên production.
Khi deploy model mới, kiểm tra kích thước, metadata, title mapping và đường dẫn
trong thư mục model.

## Công bố sau khi vá

Sau khi bản vá được phát hành, maintainer có thể công bố tóm tắt lỗ hổng và
commit đã vá. Không công bố thông tin cá nhân của người báo cáo trừ khi họ đồng ý.
