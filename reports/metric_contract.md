# Metric Contract cá nhân — T11 · Post-label Error Review Prioritizer

**Trạng thái:** Khai báo phương pháp dựa trên phiên bản PoC đã thực hiện; chưa có kết quả chấm chính thức do ground truth ẩn không được phát trong repository học viên. Thời điểm đóng băng protocol ban đầu chưa có bằng chứng xác thực, do đó không tuyên bố rằng tài liệu này đã được chốt trước khi xem kết quả.

| Mục                                 | Khai báo của người thực hiện                                                                                                                                                                                                                               |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Track                               | **T11 — Post-label Error Review Prioritizer**                                                                                                                                                                                                              |
| Primary metric                      | **Error Recall@B** (`src/metrics/tracks.py::eval_t11`)                                                                                                                                                                                                     |
| Tăng tốt hay giảm tốt?              | **higher**                                                                                                                                                                                                                                                 |
| Đơn vị đánh giá                     | Một `item_id`: `ann_id` cho nhãn bbox hiện hữu; `img:<image_id>` cho trường hợp nghi thiếu bbox                                                                                                                                                            |
| Công thức + numerator / denominator | `Error Recall@B = số item_id có lỗi thật xuất hiện trong top-B / tổng số item_id có lỗi thật trong heldout`; numerator = số lỗi tìm được, denominator = tổng lỗi thật trong pool heldout                                                                   |
| Metric phụ                          | `Precision@B = số lỗi thật trong top-B / B`; `Error-type coverage = số loại lỗi có ít nhất một trường hợp tìm được / tổng số loại lỗi trong ground truth`                                                                                                  |
| Cách ghép prediction ↔ GT           | Evaluator đối chiếu **chính xác `item_id`**, không dùng IoU để khớp prediction với ground truth. IoU chỉ được dùng **nội bộ thuật toán** khi đối chiếu bbox annotation và detector prediction                                                              |
| Candidate pool cố định              | Các `ann_id` của ảnh thuộc split `heldout` cùng các `img:<image_id>` thuộc heldout, lấy từ `fixtures/t11_label_errors/`                                                                                                                                    |
| Review budget B / K                 | Queue chạy demo có **B = 10** theo `configs/tracks/t11.yaml`. Quy tắc tài liệu T11: `B = max(10, 10% × N)`; khi đánh giá phải ghi rõ B thực tế evaluator sử dụng. Không giả định B của demo và B evaluator luôn bằng nhau                                  |
| Baseline                            | Random ranking, `seed=42`, module `src.examples.random_baseline`; không dùng ground truth để chọn mẫu                                                                                                                                                      |
| PoC / suspicion scoring             | So khớp IoU annotation–prediction; class disagreement khi IoU ≥ 0.5; weak match khi IoU dưới 0.3; duplicate cùng class nếu IoU > 0.85; missing annotation nếu prediction `conf ≥ 0.75` nhưng không khớp annotation ở IoU ≥ 0.3. Điểm cao được review trước |
| Seed                                | **42**                                                                                                                                                                                                                                                     |
| Threshold policy                    | Các ngưỡng trên là cấu hình heuristic đã sử dụng. **Chưa có bằng chứng về quá trình tune có kiểm soát trên dev hoặc thời điểm freeze**, nên không nhận là được tối ưu trên heldout. Không điều chỉnh sau khi tiếp cận GT ẩn                                |
| Eval split (không dùng để tune)     | **heldout** theo `configs/tracks/t11.yaml`, khoảng 30% ảnh theo mô tả đề; N chính xác cần lấy từ dữ liệu hoặc output evaluator                                                                                                                             |
| Chỉ số lỗi xấu                      | False alarm/Precision@B; lỗi thật bị bỏ sót ngoài top-B; sửa sai do con người (`wrong-correction rate`, chưa có GT độc lập để tính)                                                                                                                        |
| Slices sẽ báo cáo (≥2)              | (1) `class_swap`; (2) `duplicate`; đồng thời phân tích `missing`/`box_shift` nếu GT evaluator có kết quả tương ứng. Phân tích minh họa thủ công không thay thế số đo heldout                                                                               |
| Độ bất định khi N nhỏ               | Nếu có GT hợp lệ: báo numerator/denominator và N, có thể bổ sung Wilson 95% CI cho tỷ lệ hoặc bootstrap theo ảnh/scene; không công bố CI khi chưa chạy                                                                                                     |
| Ngày giờ chốt + người chốt          | Người thực hiện: **Lê Việt Long (2A202603043)**. Ngày giờ freeze gốc không được ghi lại; giữ nguyên threshold đã sử dụng và không tuyên bố chốt từ trước nếu thiếu bằng chứng                                                                              |

## Điều kiện bảo đảm tính công bằng

1. Baseline và PoC phải được đánh giá trên **cùng candidate pool, cùng heldout, cùng seed và cùng ngân sách B**.
2. Không đọc `fixtures/*/gt/` trong `src/pipeline.py`; không suy ra số điểm chính thức từ 6 chỉnh sửa Human Review.
3. `reports/metrics_baseline.json`, `reports/metrics_poc.json` và `reports/table1_baseline_vs_poc.md` chỉ được tạo bằng evaluator/compare khi có GT được giảng viên cung cấp; **không tự điền số liệu ước đoán**.
4. Nếu baseline bằng 0, báo nguyên giá trị 0, không tính tỷ lệ phần trăm cải thiện thiếu ý nghĩa.

## Tình trạng chứng cứ

- Đã xác nhận pipeline T11 chạy offline với `status=0`; pytest toàn bộ không có FAILED.
- Đã áp dụng 6 chỉnh sửa Human Review, gồm 3 `edit` và 3 `reject`, được kiểm tra qua `out/poc/changed_labels.csv`.
- **Chưa có Error Recall@B / Precision@B chính thức** vì ground truth ẩn không nằm trong repo học viên.

**Nguồn đối chiếu:** `docs/tracks/T11.md`, `configs/tracks/t11.yaml`, `src/metrics/tracks.py` và `reports/README.md` trong repository T11.
