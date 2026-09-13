# AI Spam Classifier

Ứng dụng Flask phân loại Email **SPAM/HAM** bằng Multinomial Naive Bayes, hỗ trợ nội dung tiếng Việt và tiếng Anh.

## Chức năng

- Dashboard thống kê Dataset, metric và lịch sử dự đoán.
- Phân loại một Email kèm xác suất, confidence và từ/cụm từ ảnh hưởng.
- Phân loại tối đa 500 Email từ CSV và tải kết quả CSV UTF-8.
- Tìm kiếm, lọc, phân trang, thêm, xóa và import Dataset.
- Huấn luyện và theo dõi trạng thái model.
- Đánh giá Accuracy, Precision, Recall, F1-score và Confusion Matrix.
- So sánh Naive Bayes, Logistic Regression và Linear SVM trên cùng dữ liệu.
- Lưu và quản lý lịch sử dự đoán đơn lẻ bằng SQLite.
- Đăng nhập, phân quyền Admin/User và quản lý trạng thái tài khoản.
- Tách Dashboard và History theo người dùng; Admin có thể xem toàn hệ thống.
- Kết nối Gmail OAuth 2.0 hoặc IMAP SSL, đồng bộ Inbox và phân loại cục bộ.
- Cách ly cục bộ Email SPAM, ghi nhận phản hồi người dùng và duyệt dữ liệu opt-in.

## Công nghệ

- **Backend:** Python, Flask, Flask-Login
- **Machine Learning:** scikit-learn, TF-IDF, Multinomial Naive Bayes
- **Data:** pandas, NumPy, joblib
- **Database:** SQLite
- **Frontend:** HTML, CSS, JavaScript, Bootstrap 5, Chart.js

## Pipeline

```text
Email
  -> Unicode NFC
  -> Làm sạch văn bản
  -> TF-IDF (Unigram + Bigram)
  -> Multinomial Naive Bayes
  -> SPAM / HAM
```

Naive Bayes là model chính. Logistic Regression và Linear SVM chỉ được huấn luyện tạm trong RAM trên trang so sánh, không ghi đè model chính.

## Cấu trúc

```text
spam_classifier/
├── app.py
├── auth.py
├── requirements.txt
├── requirements-lock.txt
├── README.md
├── database/
│   ├── db.py
│   └── database.db
├── dataset/
│   └── spam_dataset.csv
├── ml/
│   ├── preprocessing.py
│   ├── train.py
│   ├── predict.py
│   ├── evaluate.py
│   └── compare_models.py
├── model/
│   ├── model.pkl
│   ├── vectorizer.pkl
│   └── model_info.json
├── templates/
├── services/
│   ├── encryption_service.py
│   ├── gmail_service.py
│   ├── imap_service.py
│   ├── mail_service.py
│   └── message_parser.py
├── static/
├── tests/
└── temp/
```

## Cài đặt

Yêu cầu Python 3.10 trở lên.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:FLASK_SECRET_KEY = "thay-bang-mot-chuoi-bi-mat-dai-va-ngau-nhien"
flask --app app create-admin
python app.py
```

Mở [http://127.0.0.1:5000](http://127.0.0.1:5000).

Lệnh `create-admin` sẽ lần lượt hỏi tên, email và mật khẩu trên terminal. Mật khẩu
không hiển thị khi nhập, phải có ít nhất 8 ký tự và chỉ được lưu dưới dạng mã băm.
Ứng dụng không có chức năng tự đăng ký; Admin tạo tài khoản mới tại trang
**Quản lý người dùng**.

Nếu model chưa tồn tại hoặc hiển thị **Cần Train lại**, mở trang **Huấn luyện** và bấm **Huấn luyện mô hình**.

## Phân quyền

- **Admin:** dùng toàn bộ chức năng, quản lý Dataset, Train, Evaluate, Compare và tài khoản.
- **User:** dùng Dashboard, dự đoán đơn/hàng loạt, History cá nhân và trang Thuật toán.
- History mới được gắn với tài khoản thực hiện. Dữ liệu cũ được giữ nguyên với `user_id` rỗng và chỉ Admin nhìn thấy.
- Hệ thống không cho tự khóa tài khoản hoặc hạ quyền Admin cuối cùng đang hoạt động.

## Kết nối hộp thư

Tạo file `.env` từ `.env.example` và điền các biến cần thiết. Sinh Fernet key một lần bằng:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Giữ nguyên `CREDENTIAL_ENCRYPTION_KEY` sau khi đã kết nối tài khoản. Nếu đổi key,
credential cũ sẽ không giải mã được. Không commit `.env`, OAuth token hoặc App Password.

### Google OAuth

1. Tạo project trong Google Cloud Console và bật **Gmail API**.
2. Cấu hình **OAuth consent screen**; nếu app ở chế độ Testing, thêm Gmail vào **Test users**.
3. Tạo OAuth Client loại **Web application**.
4. Thêm Authorized redirect URI chính xác:
   `http://127.0.0.1:5000/mail/google/callback`.
5. Điền Client ID và Client Secret vào `.env`, sau đó chạy lại Flask.

Scope ứng dụng yêu cầu chỉ là `gmail.readonly`. Mỗi lần bấm Đồng bộ chỉ đọc tối đa
50 thư gần nhất trong Inbox, không xóa, di chuyển, tải attachment hoặc đổi nhãn Gmail.

## Quarantine và phản hồi

Email được model dự đoán `spam` sẽ tự động vào **Quarantine** trong SQLite. Đây chỉ
là trạng thái cục bộ; ứng dụng không di chuyển, xóa hoặc gắn nhãn thư thật trên Gmail/IMAP.
Kết quả ban đầu của model luôn được giữ riêng với nhãn xác nhận của người dùng.

Người dùng có thể xác nhận SPAM/HAM và tùy chọn cho phép dùng nội dung để cải thiện
mô hình. Chỉ feedback có opt-in mới xuất hiện tại **Phản hồi mô hình** của Admin.
Khi Admin duyệt, hệ thống kiểm tra SHA-256 và nội dung tương đương trước khi append
vào Dataset. Model không tự train; trạng thái sẽ chuyển sang **Cần Train lại** để
Admin chủ động huấn luyện sau khi rà soát dữ liệu.

### IMAP

Mở **Hộp thư → Kết nối IMAP**, nhập host, port SSL (thường là `993`), username và
App Password. Kết nối được kiểm tra trước khi lưu; App Password được mã hóa và không
hiển thị lại. Nên dùng App Password thay vì mật khẩu chính của tài khoản.

Lỗi thường gặp:

- `Thiếu CREDENTIAL_ENCRYPTION_KEY`: chưa điền key Fernet trong `.env` hoặc chưa restart Flask.
- `redirect_uri_mismatch`: URI trên Google Cloud khác URI trong `.env`.
- Google không trả refresh token: gỡ quyền kết nối rồi cấp quyền lại với consent.
- IMAP login thất bại: sai host/port, IMAP chưa bật hoặc App Password không hợp lệ.
- Không thể Sync: model chưa huấn luyện; Admin cần huấn luyện model trước.

## Kiểm thử

```powershell
.\venv\Scripts\python.exe -m compileall -q app.py auth.py database ml services tests
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Dataset

File `dataset/spam_dataset.csv` cần hai cột:

```csv
label,text
spam,"Congratulations! You won a prize."
ham,"Meeting tomorrow morning."
```

Nhãn hợp lệ là `spam` và `ham`.

## Batch CSV

Cột `text` là bắt buộc, `subject` là tùy chọn:

```csv
subject,text
"Prize","Claim your free prize."
"Meeting","Meeting tomorrow morning."
```

Hoặc:

```csv
text
"Claim your free prize."
"Meeting tomorrow morning."
```

Mỗi lần xử lý tối đa 500 Email. Kết quả batch không được ghi vào History; ứng dụng tạo file tải xuống trong `temp/`.

## Đánh giá

Các metric sử dụng lớp `spam` làm lớp dương:

- Accuracy
- Precision
- Recall
- F1-score
- Confusion Matrix

Ba thuật toán trên trang **So sánh thuật toán** dùng cùng Dataset hợp lệ, split 80/20, `random_state=42` và TF-IDF Unigram + Bigram. Kết quả được xếp hạng theo F1-score.

## Hạn chế

- Chất lượng phụ thuộc vào độ đa dạng và độ chính xác của Dataset.
- Dataset hiện tại có các mẫu lặp; metric từ split ngẫu nhiên có thể lạc quan nếu mẫu giống nhau xuất hiện ở cả Training và Testing.
- Dataset tiếng Việt cần thêm dữ liệu thực tế để tăng khả năng tổng quát.
- Chưa có cross-validation hoặc hyperparameter tuning.
- Gmail chỉ dùng quyền đọc; Quarantine không tác động lên hộp thư ở máy chủ.

## Hướng phát triển

- Bổ sung Dataset tiếng Việt chất lượng cao.
- Thêm cross-validation và tối ưu siêu tham số.
- Tích hợp Email API và xác thực đa yếu tố.
- Đóng gói triển khai bằng Docker hoặc dịch vụ cloud.
