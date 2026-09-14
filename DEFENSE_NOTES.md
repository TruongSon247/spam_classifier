# Ghi chú bảo vệ đề tài

## Bài toán là gì?

Phân loại nội dung Email thành hai nhãn SPAM và HAM để hỗ trợ nhận diện thư rác.

## Tại sao là supervised learning?

Model học từ các Email đã có nhãn đúng `spam` hoặc `ham`, sau đó dự đoán nhãn cho Email mới.

## Classification hay Regression?

Đây là classification nhị phân vì đầu ra là một trong hai lớp rời rạc, không phải một giá trị liên tục.

## Dataset có định dạng gì?

CSV gồm hai cột `label` và `text`. Label hợp lệ chỉ là `spam` hoặc `ham`.

## Train/Test split như thế nào?

Dữ liệu được chia có phân tầng khoảng 80/20, `random_state=42`, để giữ tỷ lệ hai lớp và tái lập kết quả.

## TF-IDF là gì?

TF-IDF biểu diễn văn bản bằng trọng số: một từ quan trọng khi xuất hiện nhiều trong tài liệu đang xét nhưng không quá phổ biến trong toàn bộ tập dữ liệu.

## Unigram và Bigram là gì?

Unigram là một từ; bigram là hai từ liền nhau. Kết hợp cả hai giúp model học từ khóa và một số cụm từ ngắn.

## Naive Bayes là gì?

Naive Bayes áp dụng định lý Bayes và giả định các đặc trưng độc lập có điều kiện theo lớp để tính xác suất phân loại.

## Tại sao chọn MultinomialNB?

MultinomialNB nhanh, dễ giải thích và phù hợp với vector đặc trưng văn bản không âm như TF-IDF, nên thích hợp cho bài tập phân loại thư rác.

## Alpha bằng 1 có ý nghĩa gì?

`alpha=1.0` là Laplace smoothing, tránh xác suất bằng 0 khi một đặc trưng chưa từng xuất hiện trong một lớp.

## Accuracy, Precision, Recall và F1 là gì?

Accuracy đo tỷ lệ dự đoán đúng; Precision đo độ chính xác của các dự đoán SPAM; Recall đo khả năng tìm đủ SPAM; F1 cân bằng Precision và Recall.

## Confusion Matrix là gì?

Ma trận gồm TN, FP, FN và TP, cho biết model đúng hoặc sai ở từng lớp. Tổng bốn ô bằng số mẫu Testing.

## False Positive là gì?

FP là Email HAM bị đánh nhầm thành SPAM. Đây là lỗi nhạy cảm vì có thể làm người dùng bỏ lỡ thư hợp lệ.

## False Negative là gì?

FN là Email SPAM bị đánh nhầm thành HAM, khiến thư rác lọt vào hộp thư thông thường.

## Gmail và IMAP dùng để làm gì?

Hai tích hợp này đưa Email thật vào pipeline dự đoán để minh họa ứng dụng. Gmail chỉ cấp quyền đọc và Quarantine chỉ là trạng thái cục bộ.

## API Key dùng để làm gì?

API Key xác thực client gọi REST API dự đoán. Database chỉ lưu hash và key đầy đủ chỉ hiển thị một lần.

## Quarantine là gì?

Quarantine tập hợp Email được model xem là SPAM để người dùng kiểm tra; ứng dụng không xóa hoặc di chuyển thư trên máy chủ.

## Feedback dùng để làm gì?

Người dùng có thể xác nhận hoặc sửa nhãn. Nội dung chỉ được đưa vào Dataset sau khi người dùng cho phép và Admin duyệt.

## Model Versioning là gì?

Mỗi lần train tạo một snapshot model, vectorizer và metadata. Chỉ một bản Active và Admin có thể rollback mà không mất lịch sử.

## Backup bảo vệ những gì?

Backup chứa database, Dataset, model, các phiên bản và manifest checksum; không chứa `.env`, token, log hoặc môi trường ảo.

## Hệ thống có những lớp bảo mật nào?

Mật khẩu được băm, credential được mã hóa, Web form có CSRF, API dùng key dạng hash, route có phân quyền, upload bị giới hạn, rate limit và security headers được bật.
