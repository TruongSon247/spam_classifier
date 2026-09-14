# Kiến trúc AI Spam Classifier

## Phạm vi

Ứng dụng Flask nguyên khối, chia module bằng Blueprint và service. SQLite lưu dữ
liệu nghiệp vụ; file joblib lưu vectorizer và Multinomial Naive Bayes. Naive Bayes
là model chính, còn Logistic Regression/Linear SVM chỉ phục vụ trang so sánh.

## Thành phần

- `app.py`: application factory, extension, database, Blueprint, context và CLI.
- `routes/`: HTTP endpoint, xác thực request và điều hướng response.
- `services/`: nghiệp vụ Mail, model registry, mã hóa, audit và backup.
- `database/db.py`: schema idempotent và truy vấn SQLite.
- `ml/`: preprocessing, train, predict, evaluate và compare.
- `templates/`, `static/`: giao diện Jinja, CSS và JavaScript.
- `model/`: model Active và các snapshot phiên bản.
- `dataset/`: nguồn dữ liệu huấn luyện có nhãn.

## Pipeline chính

```text
Email
  -> Chuẩn hóa Unicode và clean_text()
  -> TF-IDF (Unigram + Bigram)
  -> Multinomial Naive Bayes
  -> SPAM / HAM + xác suất + confidence
```

## Flow hộp thư

```text
Gmail readonly / IMAP SSL
  -> Đồng bộ metadata và nội dung text
  -> Áp dụng Whitelist / Blacklist
  -> Dự đoán Naive Bayes vẫn được lưu riêng
  -> Danh sách thường hoặc Quarantine cục bộ
  -> Người dùng phản hồi nhãn
```

## Flow huấn luyện

```text
Dataset CSV
  -> Validate label/text
  -> Split có phân tầng 80/20
  -> Fit TF-IDF trên Training
  -> Train MultinomialNB(alpha=1.0)
  -> Evaluate trên Testing
  -> Snapshot Model Version
  -> Cài làm Active Model
```

## Flow phản hồi

```text
User Feedback
  -> Kiểm tra quyền cho phép huấn luyện
  -> Admin Review
  -> Chống trùng bằng hash/nội dung
  -> Append Dataset
  -> Trạng thái Cần Train lại
  -> Admin chủ động Train
```

## Ranh giới an toàn

- Web dùng session, Flask-Login, phân quyền server-side và CSRF.
- REST API tách Blueprint, không dùng CSRF nhưng bắt buộc API Key cho predict.
- OAuth credential/App Password được mã hóa bằng Fernet trước khi lưu.
- Gmail dùng scope `gmail.readonly`; thao tác ẩn và Quarantine không sửa hộp thư thật.
- Backup được kiểm tra checksum, schema, Dataset và model trước khi Restore.
