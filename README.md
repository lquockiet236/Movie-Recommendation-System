# Hệ thống gợi ý phim

Ứng dụng web Django giúp khám phá phim và nhận gợi ý dựa trên nội dung phim. Dự án có sẵn model mẫu để chạy offline; có thể cấu hình TMDB để duyệt dữ liệu trực tuyến và sử dụng các chức năng cá nhân hóa.

## Chức năng

- Tìm phim tương tự theo tên phim, với autocomplete và xử lý tên gần đúng.
- Duyệt danh sách phim, tìm kiếm và lọc theo thể loại hoặc năm.
- Xem thông tin chi tiết, lưu phim yêu thích và đánh giá phim khi đăng nhập.
- Trang gợi ý dành riêng cho người dùng, dựa trên phim đã yêu thích, đánh giá và tương tác.
- Model mẫu gồm **6.248 phim**, lưu các phim lân cận đã tính trước để suy luận nhanh.
- Có thể huấn luyện model mới từ bộ dữ liệu dạng TMDB.

## Công nghệ

- Python 3.12+
- Django 6, Gunicorn và WhiteNoise
- NumPy, pandas, PyArrow và SciPy cho tải/suy luận model
- SQLite cho tài khoản, phiên đăng nhập, yêu thích, đánh giá và lịch sử tương tác
- TMDB API (tùy chọn; cần `TMDB_ACCESS_TOKEN` để dùng dữ liệu trực tuyến)

## Chạy local trên Windows

Mở PowerShell tại thư mục gốc của project:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Mở <http://127.0.0.1:8000/>.

Không có `TMDB_ACCESS_TOKEN`, ứng dụng vẫn chạy với model mẫu và dữ liệu offline. Để bật TMDB, đặt token trong cùng cửa sổ PowerShell trước khi khởi động server:

```powershell
$env:TMDB_ACCESS_TOKEN = "TMDB_READ_ACCESS_TOKEN"
python manage.py runserver
```

Không đưa token hoặc `SECRET_KEY` thật vào Git. `.env.example` liệt kê các biến tham khảo; Django trong project đọc biến từ môi trường hệ điều hành, không tự nạp file `.env`.

### Linux/macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Các trang và API

| Đường dẫn | Mô tả |
|---|---|
| `/` | Chuyển tới trang khám phá phim; yêu cầu POST vẫn hỗ trợ gửi tên phim để nhận gợi ý |
| `/movies/` | Duyệt, tìm kiếm và lọc phim |
| `/movies/<tmdb_id>/` | Chi tiết phim |
| `/recommendation` | Form nhập tên phim để tìm phim tương tự |
| `/for-you/` | Gợi ý cá nhân hóa, yêu cầu đăng nhập |
| `/favorites/` | Danh sách phim yêu thích |
| `/accounts/login/`, `/accounts/signup/` | Đăng nhập và đăng ký |
| `/api/search/?q=matrix` | API autocomplete; truy vấn từ 2 ký tự trở lên |
| `/api/model-status/` | Trạng thái tải model |
| `/api/health/` | Health check cho deployment |

Trang `/movies/` và chi tiết phim dùng TMDB khi đã cấu hình token; nếu không, ứng dụng thử lấy dữ liệu từ model offline. Gợi ý tại `/recommendation` dùng model suy luận offline. Trang `/for-you/` sử dụng dữ liệu tương tác của người dùng và TMDB.

## Model và huấn luyện

Model mẫu nằm trong `demo_model/`. Model được tải nền một lần trong mỗi process; endpoint `/api/model-status/` cho biết trạng thái tải. Model runtime cần metadata, ánh xạ tên phim và dữ liệu tương đồng (top-K neighbours hoặc ma trận similarity).

Để huấn luyện model riêng, cài thêm dependencies:

```powershell
python -m pip install -r requirements-train.txt
python training/train.py .\TMDB_movie_dataset_v11.csv -o .\models
```

Lệnh trên dùng cấu hình mặc định: ngưỡng 50 lượt bình chọn và tối đa 50.000 phim. Dataset cần có cấu trúc cột tương thích với TMDB Movie Dataset, gồm thông tin như `title`, `status`, `vote_count`, `genres`, `keywords`, `production_companies`, `production_countries`, `overview` và `tagline`.

Ứng dụng mặc định tìm model trong `models/` rồi tới `demo_model/`. Để chỉ định vị trí khác, đặt `MODEL_DIR` trước khi chạy:

```powershell
$env:MODEL_DIR = "$PWD\models"
python manage.py runserver
```

Xem toàn bộ tùy chọn huấn luyện và hướng dẫn dữ liệu trong [training/guide.md](training/guide.md).

## Cấu hình

Đặt các biến này trong môi trường chạy ứng dụng (hoặc phần Environment của nền tảng deploy):

| Biến | Ý nghĩa |
|---|---|
| `SECRET_KEY` | Khóa Django; phải đặt giá trị riêng khi chạy production |
| `DEBUG` | Mặc định bật khi phát triển; production cần đặt `False` |
| `ALLOWED_HOSTS` | Danh sách hostname, phân cách bằng dấu phẩy |
| `CSRF_TRUSTED_ORIGINS` | Các origin tin cậy cho request CSRF qua HTTPS |
| `TMDB_ACCESS_TOKEN` | Read access token để bật TMDB API |
| `MODEL_DIR` | Thư mục model; nếu không có thì ứng dụng tìm model mẫu |
| `RECOMMENDATION_COUNT` | Số kết quả gợi ý; mặc định `15` |
| `SQLITE_PATH` | Đường dẫn SQLite; mặc định là `db.sqlite3` |
| `SECURE_SSL_REDIRECT` | Chuyển hướng HTTPS trong production; mặc định bật khi `DEBUG=False` |
| `MODEL_URL` | Tùy chọn riêng trong `render.yaml`: URL archive model tải lúc build |

## Kiểm tra

```powershell
python manage.py check
python manage.py test
```

## Deploy

### Render

Project có sẵn [render.yaml](render.yaml). Tạo Web Service từ repository để Render dùng cấu hình này. Thiết lập `ALLOWED_HOSTS` cho domain của bạn; `MODEL_URL` chỉ cần khi muốn tải model archive riêng trong lúc build. Health check được cấu hình tại `/api/health/`.

### Docker

```powershell
docker build -t movie-recommendation-system .

$secret = python -c "import secrets; print(secrets.token_urlsafe(50))"
docker run --rm -p 8000:8000 `
  -e "SECRET_KEY=$secret" `
  -e "ALLOWED_HOSTS=localhost,127.0.0.1" `
  -e "SECURE_SSL_REDIRECT=False" `
  movie-recommendation-system
```

`SECURE_SSL_REDIRECT=False` phù hợp cho chạy local qua HTTP; khi deploy sau proxy HTTPS, cấu hình theo môi trường thực tế. Image khởi chạy migrations và Gunicorn với một worker, bốn threads; model được giữ trong process nên tăng số worker cũng làm tăng lượng model nằm trong bộ nhớ.

## Cấu trúc thư mục

```text
movie_recommendation/   Cấu hình Django, URL và WSGI
recommender/            Views, model dữ liệu, templates và tests
training/               Huấn luyện và suy luận model
demo_model/             Model mẫu
static/                 Static files
assets/                 Tài nguyên dự án
manage.py
requirements.txt        Dependencies chạy ứng dụng
requirements-train.txt  Dependencies bổ sung để huấn luyện
render.yaml             Cấu hình Render
Dockerfile              Cấu hình Docker
```

## Tài liệu

- [Hướng dẫn dự án](PROJECT_GUIDE.md)
- [Hướng dẫn huấn luyện](training/guide.md)
- [Đóng góp cho dự án](CONTRIBUTING.md)
- [Lịch sử thay đổi](CHANGELOG.md)
- [Báo cáo bảo mật](SECURITY.md)

## Dữ liệu và giấy phép

Dữ liệu phim và poster trực tuyến được cung cấp bởi TMDB. Sản phẩm sử dụng TMDB API nhưng không được TMDB chứng thực hoặc chứng nhận. Xem [điều khoản TMDB](https://www.themoviedb.org/api-terms-of-use).

Mã nguồn theo giấy phép trong [LICENSE](LICENSE). Giấy phép mã nguồn không đồng nghĩa với quyền phân phối dữ liệu phim hoặc hình ảnh từ TMDB.
