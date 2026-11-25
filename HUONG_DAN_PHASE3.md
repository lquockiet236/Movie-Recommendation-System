# Giai đoạn 3 — Gợi ý cá nhân hóa từ TMDB

## Cài đặt
1. Giải nén dự án. Không sao chép `.venv` từ máy cũ.
2. Nếu cần giữ tài khoản/dữ liệu thật, **sao lưu** `db.sqlite3` từ dự án Phase 2 và đặt cạnh `manage.py` (không đưa `.env` hoặc token vào ZIP chia sẻ).
3. PowerShell trong thư mục chứa `manage.py`:
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   $env:TMDB_ACCESS_TOKEN="YOUR_TMDB_READ_ACCESS_TOKEN"
   python manage.py runserver"
   python manage.py migrate
   python manage.py runserver
   ```
4. Đăng nhập, truy cập `http://127.0.0.1:8000/for-you/`.
5. Thử yêu thích/đánh giá vài phim, tải lại trang Gợi ý dành cho bạn và so sánh với một tài khoản khác.

## Thuật toán
- Nguồn phim: TMDB API; SQLite chỉ lưu tài khoản, yêu thích, rating và lịch sử tương tác phim.
- Hạt giống: yêu thích (trọng số 3), đánh giá 4–5 sao (trọng số tăng theo sao), lượt mở chi tiết gần đây (0.25, mỗi phim tính một lần).
- Ứng viên: Similar của tối đa 3 phim hạt giống, Discover theo tối đa 3 thể loại ưu tiên, Popular để mở rộng.
- TF-IDF + cosine tính trên hồ sơ sở thích và mô tả/thể loại của danh sách ứng viên; thể loại và từ khóa có trọng số lớn hơn mô tả.
- Điểm = 0.5 * cosine + 0.3 * thể loại + 0.2 * chất lượng (điểm TMDB có điều chỉnh theo số lượt vote).
- Loại phim đã yêu thích/đánh giá; khi chưa có tín hiệu, hiển thị phim phổ biến (cold start).
- Chỉ có tương tác xem chi tiết không đồng nghĩa đã xem phim thật.

## Lưu ý
- Đây là thuật toán gợi ý dựa trên nội dung và hồ sơ sở thích, **không phải collaborative filtering**. Trọng số khởi tạo chưa được tối ưu trên dữ liệu đánh giá.
- TMDB có thể trả mô tả tiếng Việt không đầy đủ; điểm tương đồng nội dung khi đó có thể kém chính xác. Có thể bổ sung fallback tiếng Anh ở giai đoạn sau.
- Cần kết nối API và token hợp lệ; dữ liệu được cache bởi `tmdb_service.py`.
- Nếu thiếu phim ứng viên, gợi ý có thể ít hơn 12 phim.
- Chạy thử: `python manage.py test recommender.tests_recommendation`.
