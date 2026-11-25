# CineRec — Hướng dẫn cài đặt và mô tả dự án

Tài liệu này mô tả phiên bản hiện tại của CineRec: cách cài đặt, chạy, cấu hình, sử dụng, kiểm thử và triển khai; đồng thời giải thích các thành phần chính và hai luồng gợi ý phim. Các lệnh dưới đây giả định đang chạy từ thư mục gốc có `manage.py`.

## 1. Tổng quan

CineRec là ứng dụng web Django kết hợp dữ liệu phim TMDB với mô hình gợi ý nội dung chạy offline. Ứng dụng cung cấp:

- Duyệt, tìm kiếm, lọc phim theo thể loại/năm và phân trang.
- Trang chi tiết phim, thao tác yêu thích và đánh giá.
- Gợi ý phim tương tự từ mô hình offline.
- Gợi ý cá nhân hóa cho tài khoản đã đăng nhập, kết hợp nội dung và tín hiệu từ người dùng tương tự.
- Đăng ký, đăng nhập, danh sách yêu thích, Django Admin và trang đánh giá thuật toán.
- API tìm kiếm nhanh, trạng thái tải mô hình và health check.

Hai nguồn dữ liệu cần phân biệt:

1. **Mô hình offline**: metadata và các phim láng giềng được tính trước, lưu trong `demo_model/` hoặc thư mục mô hình tùy chỉnh. Dùng cho luồng tìm phim tương tự và làm dữ liệu dự phòng khi duyệt phim không có token TMDB.
2. **TMDB API**: cung cấp dữ liệu phim trực tuyến khi cấu hình `TMDB_ACCESS_TOKEN`. Dùng cho duyệt phim và ứng viên của gợi ý cá nhân hóa.

SQLite lưu dữ liệu tài khoản, session, phim được lưu trong cơ sở dữ liệu, yêu thích, đánh giá và tương tác. SQLite không thay thế danh mục Parquet/NumPy của mô hình offline.

## 2. Yêu cầu

- Python 3.12 trở lên được khuyến nghị; Django 6 yêu cầu Python mới hơn các bản Django trước.
- pip và `venv` (đi kèm Python).
- Kết nối Internet nếu muốn tải phim trực tiếp từ TMDB hoặc cài các gói.
- Token TMDB Read Access tùy chọn để bật dữ liệu trực tuyến.
- Dữ liệu CSV chỉ cần khi tự huấn luyện mô hình; không cần để chạy mô hình mẫu.

## 3. Cài đặt và chạy trên Windows

### Lần đầu lấy project từ GitHub

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Thay `OWNER/REPOSITORY` bằng tài khoản và tên repository GitHub của bạn; `REPOSITORY` ở lệnh `cd` là tên thư mục được tạo sau khi clone. Nếu repository riêng tư, người dùng cần được cấp quyền GitHub.

Mở <http://127.0.0.1:8000/movies/> trong trình duyệt. Đường dẫn `/` chuyển hướng đến `/movies/`. Mô hình mẫu đã nằm trong repository nên có thể dùng luồng offline ngay; không cần tải CSV hay TMDB token để khởi động.

### Cập nhật project khi có commit mới

Trong thư mục đã clone, dừng server đang chạy bằng `Ctrl+C`, mở PowerShell tại thư mục đó rồi chạy:

```powershell
git status
git pull
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Nếu `git status` cho thấy bạn có thay đổi cục bộ, hãy commit hoặc sao lưu chúng trước khi pull. Có thể bỏ qua cài lại requirements nếu `requirements.txt` không đổi; luôn chạy `migrate` sau khi cập nhật để áp dụng migration mới. Nếu pull có thay đổi migration, dữ liệu schema trong database cục bộ sẽ được cập nhật.

### Dữ liệu và cấu hình trên máy mỗi người

- `.venv/`, `.env` và `db.sqlite3` bị loại khỏi Git. Mỗi người tạo môi trường ảo và database riêng; tài khoản, yêu thích, đánh giá và session không được chia sẻ qua `git pull`.
- Tài khoản quản trị cũng thuộc database cục bộ. Muốn vào trang admin, mỗi người tự tạo tài khoản bằng `python manage.py createsuperuser`.
- Không có TMDB token thì dùng được mô hình offline. Muốn tải dữ liệu trực tuyến, mỗi người tự thiết lập token trong PowerShell trước khi chạy server; không commit token lên GitHub.
- `.env.example` chỉ là tài liệu tham khảo cho biến môi trường; ứng dụng không tự đọc file `.env`.

Nếu PowerShell chặn kích hoạt môi trường ảo, có thể cho phép script trong phiên hiện tại rồi kích hoạt lại:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### Dùng TMDB API (tùy chọn)

Tạo API Read Access Token trong phần cài đặt API của tài khoản TMDB. Đặt token vào biến môi trường **trước khi chạy server**:

```powershell
$env:TMDB_ACCESS_TOKEN = "YOUR_TMDB_READ_ACCESS_TOKEN"
python manage.py runserver
```

Không đưa token thật vào mã nguồn, HTML/JavaScript, Git hoặc tài liệu được chia sẻ. Đổi token nếu token từng được ghi trực tiếp vào tài liệu hoặc công khai.

Không có token thì ứng dụng vẫn chạy với mô hình mẫu. Trang `/movies/` dùng danh mục offline nếu mô hình có sẵn; các tính năng cần dữ liệu TMDB trực tuyến, đặc biệt gợi ý cá nhân hóa, cần token hợp lệ.

> `.env.example` là danh sách biến cấu hình và mẫu tham khảo. Django settings hiện tại đọc trực tiếp biến môi trường của tiến trình; chỉ tạo file `.env` không tự nạp giá trị vào ứng dụng.

### Tạo tài khoản quản trị

Lệnh sau không bắt buộc để dùng các trang công khai; cần thực hiện nếu muốn vào Django Admin hoặc dashboard dành cho nhân viên:

```powershell
python manage.py createsuperuser
```

Sau đó mở `/admin/` để dùng Django Admin hoặc `/admin/dashboard/` để xem dashboard riêng của ứng dụng.

## 4. Các trang và luồng sử dụng

| Đường dẫn | Quyền truy cập | Chức năng |
|---|---|---|
| `/` | Công khai | GET chuyển hướng đến `/movies/`; POST vẫn hỗ trợ gửi yêu cầu gợi ý offline cũ. |
| `/movies/` | Công khai | Duyệt phim, tìm theo tên, lọc thể loại/năm, phân trang. Có token thì lấy dữ liệu TMDB; không có token thì dùng dữ liệu mô hình offline. |
| `/movies/<tmdb_id>/` | Công khai | Xem thông tin phim; người đã đăng nhập có thể lưu yêu thích và đánh giá. |
| `/recommendation` | Công khai | Nhập phim để tìm các phim tương tự từ mô hình offline. GET mở biểu mẫu; POST tạo kết quả. |
| `/accounts/signup/` | Công khai | Tạo tài khoản. |
| `/accounts/login/` | Công khai | Đăng nhập. |
| `/accounts/logout/` | Đã đăng nhập | Đăng xuất qua POST. |
| `/favorites/` | Đã đăng nhập | Xem, mở chi tiết hoặc bỏ phim khỏi danh sách yêu thích. |
| `/for-you/` | Đã đăng nhập | Gợi ý cá nhân hóa dựa trên yêu thích, đánh giá và tương tác. |
| `/admin/` | Nhân viên | Django Admin để quản lý tài khoản và bản ghi `Movie`. |
| `/admin/dashboard/` | Nhân viên | Thống kê cơ sở dữ liệu và trạng thái mô hình. |
| `/evaluation/` | Nhân viên | Bảng đánh giá offline các thuật toán gợi ý. |

Đánh giá phim hiện là một lần cho mỗi tài khoản/phim; không thể gửi đánh giá thứ hai cho cùng phim. Lịch sử tìm kiếm cũ còn trong cơ sở dữ liệu để tương thích nhưng không được cập nhật hoặc hiển thị như một tính năng tìm kiếm.

## 5. Các API

| Endpoint | Phương thức | Mô tả |
|---|---|---|
| `/api/search/?q=<từ-khóa>` | GET | Tìm tiêu đề trong mô hình offline để phục vụ autocomplete. Truy vấn ngắn hơn 2 ký tự trả danh sách rỗng. |
| `/api/model-status/` | GET | Trả trạng thái tải mô hình: `loading`, `ready`, `missing` hoặc `error`. |
| `/api/health/` | GET | Health/readiness check. Trả `healthy` khi mô hình sẵn sàng, `starting` trong lúc tải và HTTP 503 khi thiếu/lỗi mô hình. |

Ví dụ trong PowerShell:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/search/?q=matrix"
Invoke-RestMethod "http://127.0.0.1:8000/api/model-status/"
Invoke-RestMethod "http://127.0.0.1:8000/api/health/"
```

## 6. Cách hệ thống gợi ý phim

### 6.1 Gợi ý tương tự từ mô hình offline

`demo_model/` đi kèm dự án để có thể dùng ngay mà không cần huấn luyện. Khi khởi động, ứng dụng tìm một thư mục mô hình hợp lệ và tải nó một lần trong background. Giao diện có thể hỏi `/api/model-status/` để biết quá trình tải.

Luồng xử lý:

1. Chuẩn hóa và tìm tên phim theo thứ tự khớp chính xác, tiền tố, chuỗi con rồi gần đúng.
2. Tra chỉ số phim trong `title_to_idx.json`.
3. Đọc hàng láng giềng tương ứng từ các mảng NumPy đã tính trước.
4. Lọc phim nguồn, lấy số lượng kết quả theo `RECOMMENDATION_COUNT` và dựng thẻ kết quả.

Phần serving không tính lại ma trận cosine cho từng yêu cầu. Mô hình top-K mặc định lưu các láng giềng gần nhất, giảm dung lượng so với ma trận đầy đủ.

### 6.2 Gợi ý cá nhân hóa

`/for-you/` xây dựng hồ sơ từ dữ liệu tài khoản:

- Yêu thích là tín hiệu tích cực mạnh.
- Đánh giá 4–5 sao góp phần tạo sở thích; phim đã đánh giá/yêu thích bị loại khỏi danh sách đề xuất.
- Các lượt mở trang chi tiết gần đây là tín hiệu yếu hơn; chúng không chứng minh người dùng đã xem phim.
- Ứng viên lấy từ phim tương tự, khám phá theo thể loại, phim phổ biến trên TMDB và phim được người dùng tương tự đánh giá cao.

Xếp hạng nội dung kết hợp độ tương đồng văn bản, độ phù hợp thể loại và chất lượng phim TMDB. Khi có đủ bằng chứng collaborative filtering, điểm kết hợp dùng 65% nội dung và 35% collaborative filtering. Hai người dùng cần có tối thiểu hai phim chung để được xem là có đủ dữ liệu so sánh. Nếu chưa có sở thích, hệ thống dùng phim phổ biến làm phương án cold-start.

Đây là hệ thống gợi ý kết hợp nội dung với user-based collaborative filtering; nó không phải mô hình neural network. Kết quả phụ thuộc vào dữ liệu tương tác sẵn có và khả năng truy cập TMDB.

### 6.3 Đánh giá thuật toán

`/evaluation/` và lệnh `evaluate_recommendations` chạy đánh giá leave-one-positive-out trên dữ liệu đánh giá trong SQLite. Content-Based và Hybrid trong báo cáo dùng metadata `Movie` đã lưu cục bộ; kết quả **không phải phép đo trực tiếp toàn bộ luồng gợi ý TMDB trực tuyến**. Khi dữ liệu không đủ, dashboard hiển thị N/A thay vì tạo số liệu giả.

## 7. Dữ liệu và cấu hình

### Cơ sở dữ liệu

Mặc định Django dùng SQLite ở `db.sqlite3` cạnh `manage.py`. Có thể đặt `SQLITE_PATH` để chỉ định vị trí khác.

Các model quan trọng trong `recommender/models.py`:

- `Movie`: metadata phim được lưu vào SQLite, phục vụ Django Admin và đánh giá offline.
- `FavoriteMovie`: phim yêu thích TMDB theo `tmdb_id`, đồng thời giữ các mục yêu thích cũ lưu theo tên.
- `MovieRating`: điểm 1–5, duy nhất theo cặp người dùng/phim.
- `MovieInteraction`: dấu vết nội bộ như xem chi tiết, yêu thích, bỏ yêu thích và đánh giá; được dùng cho gợi ý.
- `SearchHistory`: model cũ còn trong schema nhưng không còn luồng giao diện/ghi lịch sử tìm kiếm.

Sau khi cập nhật mã nguồn hoặc nhận migration mới, chạy:

```powershell
python manage.py migrate
```

Sao lưu `db.sqlite3` trước khi nâng cấp hoặc di chuyển dữ liệu tài khoản. Không gửi database thật vào kho mã nguồn hoặc ZIP công khai.

### Biến môi trường

| Biến | Ý nghĩa |
|---|---|
| `SECRET_KEY` | Khóa Django. Bắt buộc phải đặt khóa riêng khi `DEBUG=False`. |
| `DEBUG` | Mặc định bật trong môi trường phát triển; phải tắt khi triển khai thật. |
| `ALLOWED_HOSTS` | Danh sách hostname được phép, phân cách bằng dấu phẩy. Cần cấu hình cho production. |
| `CSRF_TRUSTED_ORIGINS` | Các origin tin cậy, gồm scheme như `https://example.com`. |
| `SECURE_SSL_REDIRECT` | Điều khiển chuyển hướng HTTPS khi `DEBUG=False`; tắt nếu chạy HTTP cục bộ không có proxy TLS. |
| `TMDB_ACCESS_TOKEN` | Bearer Read Access Token để gọi TMDB; tùy chọn khi chỉ dùng mô hình offline. |
| `MODEL_DIR` | Thư mục mô hình ưu tiên. Đường dẫn tương đối tính từ thư mục dự án. |
| `MODEL_URL` | Tùy chọn ở bước build trên Render để tải archive mô hình; ứng dụng không tải mô hình này khi phục vụ request. |
| `RECOMMENDATION_COUNT` | Số kết quả của luồng gợi ý offline; mặc định `15`. |
| `SQLITE_PATH` | Đường dẫn tùy chọn đến file SQLite. |

Ứng dụng ưu tiên mô hình ở `MODEL_DIR`, sau đó tìm các thư mục tương thích như `models/`, `demo_model/` và vị trí hỗ trợ ngược. Thư mục mô hình phải có `config.json`, `title_to_idx.json`, metadata Parquet và dữ liệu độ tương đồng hợp lệ.

## 8. Huấn luyện mô hình riêng

Huấn luyện là tùy chọn. Cài thêm dependency:

```powershell
pip install -r requirements-train.txt
```

Chuẩn bị CSV theo cấu trúc TMDB Movies Dataset, thường là `TMDB_movie_dataset_v11.csv`, rồi chạy:

```powershell
python training\train.py .\TMDB_movie_dataset_v11.csv -o .\models
```

Các tham số hữu ích:

```powershell
python training\train.py --help
python training\train.py .\TMDB_movie_dataset_v11.csv -o .\models -q high -m 10000
python training\train.py .\TMDB_movie_dataset_v11.csv -o .\models -q medium -m 50000 -k 50 --components 500
```

- Chất lượng `low`, `medium`, `high` tương ứng ngưỡng tối thiểu 5, 50, 500 lượt vote.
- Mặc định giới hạn 50.000 phim, lưu 50 láng giềng mỗi phim, dùng SVD 500 chiều và xử lý theo khối 1.024 hàng.
- `--no-svd` bỏ SVD; `--legacy-matrix` tạo ma trận similarity đầy đủ, tốn bộ nhớ lớn hơn đáng kể.
- Huấn luyện cần `requirements-train.txt`; chạy website chỉ cần `requirements.txt`.

Các file phục vụ inference gồm `movie_metadata.parquet`, `title_to_idx.json`, `config.json`, `neighbors_idx.npy` và `neighbors_scores.npy` (hoặc định dạng ma trận legacy). File `.pkl` được tạo trong quá trình train chỉ phục vụ retraining; không cần để chạy website và chỉ nên mở pickle từ nguồn đáng tin.

Sau khi train vào `models/`, có thể chạy với:

```powershell
$env:MODEL_DIR = "models"
python manage.py runserver
```

## 9. Cấu trúc mã nguồn

```text
movie-recommendation-system/
├── movie_recommendation/       # Settings, URL gốc, ASGI/WSGI
├── recommender/
│   ├── views.py                # Mô hình offline, trang gợi ý và API trạng thái
│   ├── tmdb_views.py           # Duyệt và chi tiết phim
│   ├── tmdb_service.py         # HTTP client/cache TMDB
│   ├── account_views.py        # Đăng ký, yêu thích, đánh giá
│   ├── recommendation_engine.py# Gợi ý cá nhân hóa
│   ├── collaborative_filtering.py
│   ├── evaluation.py           # Đánh giá offline
│   ├── models.py               # Schema dữ liệu Django
│   ├── migrations/             # Lịch sử schema
│   ├── management/commands/    # Lệnh quản trị, gồm evaluate_recommendations
│   ├── templates/recommender/  # Giao diện HTML
│   └── tests*.py               # Kiểm thử web, gợi ý, đánh giá
├── training/
│   ├── train.py                # Pipeline huấn luyện
│   ├── infer.py                # Dùng model độc lập ngoài Django
│   └── guide.md                # Tùy chọn huấn luyện nâng cao
├── demo_model/                 # Mô hình mẫu đi kèm
├── static/                     # Tài nguyên tĩnh
├── requirements.txt            # Dependency phục vụ web
├── requirements-train.txt      # Dependency huấn luyện bổ sung
├── .env.example                # Danh sách biến môi trường tham khảo
├── Dockerfile, render.yaml     # Cấu hình triển khai
└── manage.py                   # Django management entry point
```

Giao diện dùng template Django với CSS/JavaScript đặt trong template; không cần frontend build tool riêng.

## 10. Kiểm thử và kiểm tra mã

```powershell
python manage.py check
python manage.py test
```

Chạy từng nhóm:

```powershell
python manage.py test recommender
python manage.py test recommender.tests_recommendation
python manage.py test recommender.tests_evaluation
python manage.py test training
```

Nếu đã cài Ruff:

```powershell
ruff check .
```

Các bài kiểm thử dùng dữ liệu/mocks cục bộ; chúng không yêu cầu gọi TMDB thật. Khi thay đổi API TMDB hoặc hành vi gợi ý, ưu tiên mock phản hồi để kết quả test ổn định.

## 11. Triển khai

Không dùng `python manage.py runserver` làm web server production. Dự án có cấu hình Render (`render.yaml`), Docker (`Dockerfile`) và Gunicorn (`Procfile`).

Trước khi public:

1. Đặt `DEBUG=False`, `SECRET_KEY` riêng và `ALLOWED_HOSTS` đúng.
2. Cấu hình HTTPS/proxy, CSRF trusted origins và biến TMDB nếu cần dữ liệu trực tuyến.
3. Bảo đảm thư mục mô hình tồn tại hoặc dùng `demo_model/`.
4. Chạy migrations và `collectstatic` theo quy trình build/release.
5. Dùng database bền vững và sao lưu; SQLite phù hợp phát triển, cần đánh giá giải pháp database production theo môi trường triển khai.
6. Kiểm tra `/api/health/` sau khi deploy.

Lệnh Docker cơ bản từ thư mục gốc:

```powershell
docker build -t cinerec .
$secret = python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
docker run --rm -p 8000:8000 `
  -e "SECRET_KEY=$secret" `
  -e "ALLOWED_HOSTS=localhost,127.0.0.1" `
  -e "SECURE_SSL_REDIRECT=False" `
  cinerec
```

Khi chạy container cục bộ qua HTTP, `SECURE_SSL_REDIRECT=False` tránh chuyển hướng lặp sang HTTPS. Với production sau proxy TLS, cấu hình theo hướng dẫn của nền tảng thay vì tắt bảo vệ HTTPS một cách mặc định.

Ứng dụng dùng một Gunicorn worker với nhiều thread trong cấu hình mẫu để tránh nạp nhiều bản mô hình vào RAM. Điều chỉnh tài nguyên và worker theo kích thước mô hình, sau khi đo trên môi trường triển khai.

## 12. Xử lý sự cố thường gặp

| Hiện tượng | Cách kiểm tra |
|---|---|
| `ModuleNotFoundError: django` | Kích hoạt đúng `.venv`, sau đó chạy `pip install -r requirements.txt`. |
| Ứng dụng báo thiếu mô hình | Kiểm tra `demo_model/` hoặc đặt `MODEL_DIR` tới thư mục có đủ artifacts; kiểm tra `/api/model-status/`. |
| Trang TMDB không tải dữ liệu | Kiểm tra `TMDB_ACCESS_TOKEN`, quyền API và kết nối Internet; lỗi HTTP được hiển thị bằng thông báo an toàn. |
| Trang cá nhân hóa báo lỗi API | Luồng này cần token TMDB hợp lệ và kết nối được API; kiểm tra log server, không gửi token vào log/chat. |
| Trang admin chuyển về đăng nhập hoặc 403 | Đăng nhập tài khoản `is_staff=True`; tạo tài khoản quản trị bằng `createsuperuser`. |
| `no such table` | Chạy `python manage.py migrate` trong đúng thư mục/môi trường. |
| Cổng 8000 đã được sử dụng | Chạy `python manage.py runserver 8001`. |
| Static file lỗi trên production | Chạy `python manage.py collectstatic --noinput` trong build và kiểm tra cấu hình WhiteNoise. |
| Lỗi khi train trên Windows | Cài dependency từ `requirements-train.txt`; nếu SciPy gặp lỗi DLL do môi trường, thử môi trường Conda như hướng dẫn đóng góp. |

## 13. Quyền riêng tư, bảo mật và ghi nhận nguồn

- Không commit `SECRET_KEY`, TMDB token, database tài khoản hoặc `.env` có dữ liệu thật.
- Token TMDB được gửi từ server tới TMDB; không đưa token vào trình duyệt.
- Chỉ dùng artifacts mô hình từ nguồn đáng tin; ứng dụng serving không cần pickle.
- Dữ liệu phim/poster được lấy từ TMDB. Khi phân phối hoặc công bố sản phẩm, tuân thủ điều khoản TMDB và yêu cầu nhận diện/attribution hiện hành.
- Báo cáo lỗ hổng bảo mật riêng tư theo hướng dẫn trong [SECURITY.md](SECURITY.md).

## 14. Tài liệu liên quan

- [README.md](README.md): giới thiệu ngắn và thông tin dự án.
- [training/guide.md](training/guide.md): chi tiết dataset, thuật toán train và tùy chỉnh mô hình.
- [CONTRIBUTING.md](CONTRIBUTING.md): quy trình phát triển và đóng góp.
- [UPGRADE_GUIDE_VI.md](UPGRADE_GUIDE_VI.md): lưu ý nâng cấp và dữ liệu cũ.
- [CHANGELOG.md](CHANGELOG.md): thay đổi theo phiên bản.
