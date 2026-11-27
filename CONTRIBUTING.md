# Đóng góp cho CineRec

Cảm ơn bạn đã muốn đóng góp cho hệ thống gợi ý phim. Hướng dẫn này mô tả cách
thiết lập môi trường, chạy kiểm tra và các quy tắc riêng của dự án.

## 1. Thiết lập môi trường

Yêu cầu khuyến nghị: Python 3.12 trên Windows, macOS hoặc Linux.

### Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### Linux/macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Mở <http://127.0.0.1:8000/>. Project đi kèm mô hình mẫu trong `demo_model/`,
nên không cần TMDB token hoặc dataset để phát triển luồng offline.

Tài khoản, database và `.venv/` là dữ liệu cục bộ. Không commit
`SECRET_KEY`, TMDB token hoặc `db.sqlite3`.

## 2. Kiểm tra trước khi tạo pull request

```powershell
python manage.py check
python manage.py migrate --check
python manage.py test
python -m pip install ruff
ruff check .
```

`python manage.py check` phát hiện lỗi settings, middleware, URL và cấu hình
static trước khi test suite chạy.

Với thay đổi deployment, thêm:

```powershell
python manage.py check --deploy
python manage.py collectstatic --noinput
```

Chỉ chạy `check --deploy` với `DEBUG=False` và `SECRET_KEY` hợp lệ.

## 3. Cấu trúc code

- `movie_recommendation/`: settings, URL gốc, ASGI và WSGI.
- `recommender/`: view, TMDB service, tài khoản, yêu thích, đánh giá và gợi ý.
- `recommender/templates/recommender/`: template Django.
- `recommender/tests*.py`: test web, gợi ý và đánh giá.
- `training/`: huấn luyện và inference độc lập.
- `demo_model/`: mô hình offline mẫu.
- `data/`: dữ liệu huấn luyện thu thập được.
- `models_tmdb_*` và `models/`: thư mục model được tạo ra.

## 4. Quy tắc khi thay đổi web app

- Không đưa toàn bộ danh mục phim vào HTML. Tìm tiêu đề qua `/api/search/`.
- Giữ đầy đủ các trạng thái model: `loading`, `ready`, `missing` và `error`.
- `/api/health/` không được lộ exception hoặc đường dẫn máy chủ.
- Luồng offline phải vẫn chạy khi không có TMDB Access Token.
- Thêm migration khi thay đổi Django model và chạy migration cục bộ trước khi
  mở pull request.
- Không commit TMDB token, Django secret hoặc database thật.
- Cập nhật template, URL và test khi thay đổi behavior người dùng.

## 5. Quy tắc khi thay đổi mô hình

Cài dependencies huấn luyện:

```powershell
python -m pip install -r requirements-train.txt
```

Xem tùy chọn:

```powershell
python training/train.py --help
python manage.py collect_train_tmdb --help
python manage.py evaluate_recommendations --help
```

Các lưu ý quan trọng:

- Mô hình serving không yêu cầu TF-IDF/SVD pickle.
- Artifact runtime gồm `config.json`, `title_to_idx.json`,
  `movie_metadata.parquet`, `neighbors_idx.npy` và `neighbors_scores.npy`.
- Cột danh mục trong DataFrame Parquet có thể trả NumPy array hoặc giá trị thiếu.
  Viết helper thống nhất thay vì chỉ kiểm tra `isinstance(value, list)`.
- Đường dẫn tương đối của mô hình được resolve theo thư mục gốc project.
- Khi đổi format model, cập nhật đồng bộ loader, training/inference và
  `demo_model/README.md`.
- Chỉ mở file pickle từ nguồn đáng tin cậy.

## 6. Viết test

Chạy toàn bộ suite:

```powershell
python manage.py test
```

Chạy theo khu vực:

```powershell
python manage.py test recommender
python manage.py test recommender.tests_recommendation
python manage.py test recommender.tests_evaluation
python manage.py test training
```

Test bug nên tái hiện trường hợp lỗi cụ thể. Nếu sửa xử lý Parquet, rating,
favorite constraint, TMDB response hoặc model-loading state thì thêm test trong
module gần nhất.

Không gọi TMDB thật trong unit test; mock TMDB service hoặc HTTP response.

## 7. Pull request

- Mô tả rõ vấn đề, giải pháp và các file thay đổi.
- Branch từ nhánh mặc định của repository.
- Giữ mỗi pull request tập trung vào một thay đổi.
- Cập nhật `[Unreleased]` trong `CHANGELOG.md` khi có thay đổi observable.
- Cập nhật README hoặc PROJECT_GUIDE khi thay đổi lệnh, API hoặc cấu hình.
- Ghi kết quả các lệnh đã chạy trong mô tả pull request.
- Đính kèm ảnh hoặc GIF ngắn nếu thay đổi giao diện.

## 8. Báo lỗi

Báo lỗi nên kèm:

- Phiên bản Python và hệ điều hành.
- Output của `python manage.py check`.
- Bước tái hiện.
- Log liên quan sau khi đã xóa token hoặc secret.
- Trạng thái `/api/model-status/` và `/api/health/`.

Vấn đề bảo mật cần báo riêng theo `SECURITY.md`, không mở issue công khai.

## 9. Quyền dữ liệu và TMDB

Project sử dụng dữ liệu và poster TMDB cho mục đích phát triển và giới thiệu.
MIT license chỉ áp dụng cho mã nguồn của dự án, không cấp quyền phân phối dữ liệu
hoặc hình ảnh TMDB.
