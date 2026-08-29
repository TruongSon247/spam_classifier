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

## Công nghệ

- **Backend:** Python, Flask
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
├── static/
└── temp/
```

## Cài đặt

Yêu cầu Python 3.10 trở lên.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Mở [http://127.0.0.1:5000](http://127.0.0.1:5000).

Nếu model chưa tồn tại hoặc hiển thị **Cần Train lại**, mở trang **Huấn luyện** và bấm **Huấn luyện mô hình**.

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
- Chưa tích hợp Email API hay mô hình NLP/Transformer.

## Hướng phát triển

- Bổ sung Dataset tiếng Việt chất lượng cao.
- Thêm cross-validation và tối ưu siêu tham số.
- Tích hợp Email API và xác thực người dùng.
- Đóng gói triển khai bằng Docker hoặc dịch vụ cloud.
