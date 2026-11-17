# Báo cáo cá nhân — T11 · Post-label Error Review Prioritizer

**Day 06 · Data Governance & Privacy · Field-to-Release PoC**

> **Hình thức:** Bài thực hành cá nhân. Phần Human Review có 6 chỉnh sửa thực tế; kết quả chấm GT ẩn sẽ do giảng viên thực hiện.

## 00 · Header

| Mục | Thông tin |
|---|---|
| Hình thức | **Cá nhân** (không có nhóm) |
| Challenge | **T11 · Post-label Error Review Prioritizer** |
| Họ tên / MSSV | **Lê Việt Long — 2A202603043** |
| Vai trò | Phát triển pipeline, thuật toán, QA, Human Review, báo cáo |

| Git repo | `K5-L2-Day6-LeVietLong-2A202603043-DataGovernanceAndPrivacy` (repo local; URL public chưa được xác nhận) |
| Tags | Chưa tạo hoặc chưa cung cấp bằng chứng tag |


## 01 · Problem statement

Chất lượng nhãn ảnh ảnh hưởng trực tiếp đến quá trình huấn luyện và đánh giá mô hình thị giác máy tính. Những lỗi như sai lớp đối tượng (*class swap*), bbox bị lệch, annotation trùng và đối tượng bị bỏ sót có thể làm sai tín hiệu huấn luyện. Khi số lượng ảnh và nhãn lớn, việc kiểm tra thủ công toàn bộ dữ liệu tốn thời gian; vì vậy cần ưu tiên những trường hợp có xác suất lỗi cao để người kiểm duyệt tập trung xử lý.

**Bài toán:** Từ tập annotation cùng prediction của một detector mô phỏng, tính **suspicion score** cho từng `item_id` và tạo danh sách top-B cần kiểm tra. Hệ thống không tự khẳng định nhãn sai chỉ dựa vào dự đoán của mô hình, mà đưa vào vòng **human-in-the-loop**.

**Đối tượng chịu ảnh hưởng:** người gán nhãn và QA, nhóm xây dựng dataset, người huấn luyện mô hình và nhóm quyết định đưa dữ liệu vào sử dụng. Hệ thống có thể bỏ sót nhãn sai (false negative) hoặc làm người kiểm tra mất công vì báo nhầm (false positive).

**Đầu vào → đầu ra:** `images.csv`, `annotations.csv`, `model_predictions.csv`, `manifest.csv` → thuật toán scoring → `ranking.csv`, `review_queue.csv`, `contact_sheet.html` → reviewer xác nhận/sửa → `clean_annotations.csv`, `changed_labels.csv`, `audit_log.jsonl`, `decision.json`.

**Decision policy trong bản PoC:** `HOLD` khi chưa review; sau review, vẫn `HOLD` cho đến khi thay đổi được kiểm chứng và có phê duyệt độc lập. Không tự động `GO` chỉ vì pipeline chạy thành công. Điều kiện `REWORK` có thể áp dụng nếu cần làm lại dữ liệu nhưng chưa được triển khai thành một nhánh chính sách đầy đủ. Việc phê duyệt sử dụng dữ liệu thật cần chủ dữ liệu và bộ phận liên quan xác nhận.

## 02 · Data & provenance

Nguồn dữ liệu là fixture **synthetic/offline** kèm repo T11; không sử dụng PII thật trong phần thực hành được mô tả. Theo `docs/tracks/T11.md`, bộ fixture có **55 ảnh**, khoảng **200 annotation bbox**, phân chia dev/heldout (heldout khoảng 30%). Chưa có kết quả đếm chính xác theo split từ môi trường thực thi nên không suy diễn số lượng.

| Split | Số mẫu N | Nguồn | License / tình trạng |
|---|---|---|---|
| dev | Không có số đếm thực tế | `fixtures/t11_label_errors/images.csv` | Fixture synthetic; README mô tả dữ liệu fixture CC0 |
| heldout | Không có số đếm thực tế (mô tả khoảng 30%) | Cùng file, `split=heldout` | Fixture synthetic; không dùng để tune |

- `annotations.csv`: `ann_id, image_id, class, x, y, w, h` — bbox theo tọa độ pixel.
- `model_predictions.csv`: `image_id, class, x, y, w, h, conf` — prediction detector mô phỏng, **không phải ground truth**.
- `images.csv`: `image_id, path, width, height, split`; các ảnh minh họa có kích thước 320×180.
- Các class quan sát được trong quá trình review: `car`, `motorbike`, `pedestrian`, `sign`. Không khẳng định đây là toàn bộ taxonomy.
- `manifest.csv` lưu provenance và hash; trước đó đã xử lý lỗi `hash_mismatch`, và bước kiểm tra/test sau cùng không còn failed. Không có log xác minh manifest riêng tại thời điểm viết báo cáo.
- Seed cố định: **42**; network bị chặn bằng `--offline`; pipeline không đọc GT ẩn.

## 03 · Research & design

### Thiết kế PoC

`Đọc input + kiểm provenance → Tính suspicion score → Xếp hạng top-B → Human Review/Override → Xuất nhãn sửa và quyết định → Audit/Report`

Thuật toán heuristic được xây dựng trong `src/pipeline.py`, không cần tải trọng số hay gọi API ngoài. Detector prediction đã có sẵn trong `model_predictions.csv`; do đó báo cáo không tuyên bố nhóm tự huấn luyện mô hình detector.

**Các tín hiệu chấm điểm:**

1. **Class disagreement:** Ghép annotation với prediction bằng IoU lớn nhất. Nếu IoU ≥ 0.5 nhưng class khác nhau, dùng confidence của prediction để nâng điểm nghi ngờ.
2. **Weak match/box issue:** Nếu một annotation không khớp prediction nào với IoU ≥ 0.3, đánh dấu nghi vấn; đây chỉ là proxy, chưa chứng minh bbox sai.
3. **Duplicate:** Hai annotation cùng class trong một ảnh có IoU > 0.85 được đánh dấu cần xem xét.
4. **Missing annotation:** Prediction có confidence ≥ 0.75 nhưng không có bbox annotation tương ứng (IoU ≥ 0.3) → tạo `item_id` dạng `img:<image_id>`.

Điểm score cao được ưu tiên trước; **score không được hiểu là xác suất lỗi đã được hiệu chuẩn**. Các ngưỡng là lựa chọn heuristic khởi đầu và chưa có chứng cứ tune chính thức trên dev. Trade-off là triển khai nhanh, tái lập tốt nhưng dễ bị false alarm khi detector dự đoán sai hoặc khi nhiều đối tượng thật chồng lấp.

### Tài liệu tham khảo kỹ thuật

- Tài liệu challenge và schema: `docs/tracks/T11.md` trong repo gốc.
- Metric và cách ghép ID: `src/metrics/tracks.py::eval_t11`.
- Các module review/decision: `src/common/review.py`, `src/common/contact_sheet.py`, `src/common/decision.py`.

## 04 · Baseline vs PoC

**Baseline:** module có sẵn `src.examples.random_baseline`, xếp hạng ngẫu nhiên với `seed=42`; đã chạy để tạo `out/baseline/ranking.csv`.

**PoC:** thuật toán suspicion score do người thực hiện cài đặt, chạy offline qua `src.main`; xuất `out/poc/ranking.csv` cùng queue và kết quả Human Review. Run cuối được chia sẻ: **`status=0`, runtime `0.545s`**.

| Metric (unit) | Baseline | PoC | So sánh |
|---|---|---|---|
| **Error Recall@B** (higher) | **Chưa có GT** | **Chưa có GT** | Không kết luận mức cải thiện |
| **Precision@B** (higher) | Chưa có GT | Chưa có GT | Chưa thể tính |
| **Error-type coverage** (higher) | Chưa có GT | Chưa có GT | Chưa thể tính |
| Runtime | Chưa có thời gian baseline được xác minh | `0.545s` cho lần chạy PoC cuối | Không suy ra runtime/100 items khi chưa xác nhận N |

**Giới hạn đánh giá:** GT (`gt_errors.csv`, `clean_annotations.csv`) nằm trong overlay riêng của giảng viên, không có ở repo học viên. Vì vậy **chưa tạo được** `reports/metrics_baseline.json`, `reports/metrics_poc.json` và bảng `src.compare` hợp lệ. Việc chạy trên cùng heldout và cùng B cần được xác nhận bằng evaluator chính thức; không sử dụng 6 chỉnh sửa thủ công để thay thế primary metric.

## 05 · Evaluation protocol

Primary metric: **Error Recall@B = số lỗi GT được tìm trong top-B / tổng số lỗi GT trong heldout**. Đơn vị đánh giá là `item_id`: `ann_id` cho annotation sẵn có hoặc `img:<image_id>` cho ảnh thiếu nhãn. Evaluator so sánh item ID chính xác, **không dùng IoU ở bước chấm GT**.

Secondary metric: **Precision@B = số lỗi GT trong top-B / B**, cùng chỉ số bao phủ loại lỗi. Bảng xếp hạng ở demo lấy top **10** (`configs/tracks/t11.yaml`, `budget: 10`). Theo đề, B chính thức phụ thuộc `max(10, 10% × N)`; số B do evaluator in ra cần được dùng khi có GT. Hai split cần tách biệt khi đánh giá; không tune trên heldout.

Lệnh đánh giá chuẩn (chỉ có kết quả khi GT do giảng viên cung cấp):

```bash
.venv/Scripts/python.exe -m src.evaluate --track t11 --pred out/baseline/ranking.csv --run-name baseline --out reports/metrics_baseline.json
.venv/Scripts/python.exe -m src.evaluate --track t11 --pred out/poc/ranking.csv --run-name poc --out reports/metrics_poc.json
.venv/Scripts/python.exe -m src.compare reports/metrics_baseline.json reports/metrics_poc.json --out reports/table1_baseline_vs_poc.md
```

Không báo khoảng tin cậy/CI chưa được tính. Khi có GT, cần ghi số lỗi trong mẫu, numerator/denominator và có thể bổ sung Wilson CI hoặc bootstrap theo ảnh để phản ánh độ bất định của tập nhỏ.

## 06 · Result slices & failure cases

Không có GT ẩn nên không thể lập bảng Recall theo loại lỗi một cách có kiểm chứng. Thay vào đó, báo cáo **bằng chứng Human Review** thực tế, không gắn nhãn đó là kết quả heldout chính thức:

| Trường hợp | Dữ liệu / nhận định | Hành động thực hiện |
|---|---|---|
| `ann_096` (`lbl_24`) | `motorbike` không phù hợp, prediction trùng vị trí chỉ `pedestrian` | `edit` → `pedestrian` |
| `ann_134` (`lbl_33`) | Tương tự, class swap | `edit` → `pedestrian` |
| `ann_109` (`lbl_28`) | Bbox trỏ tới ô tô nhưng class gốc `motorbike` | `edit` → `car` |
| `ann_d02` (`lbl_09`) | Bbox trùng `ann_032`, IoU xấp xỉ 0.955 | `reject` nhãn thừa |
| `ann_d00` (`lbl_16`) | Bbox trùng `ann_058`, IoU xấp xỉ 0.937 | `reject` nhãn thừa |
| `ann_186` (`lbl_48`) | Bbox trùng `ann_185`, IoU xấp xỉ 0.85 | `reject` nhãn thừa |

**Tổng số chỉnh sửa được pipeline ghi nhận: 6**, gồm **3 `edit` và 3 `reject`**, trích từ kết quả thực tế `out/poc/changed_labels.csv`. Các mục được `approve` không phải chỉnh sửa.

**Failure mode 1 — Missing chưa được xử lý đầy đủ:** `img:lbl_43` bị xếp Rank 1 vì prediction `sign` confidence 0.990 không khớp annotation hiện hữu; annotator chỉ có `car` và `motorbike`. Tuy nhiên, pipeline `review()` chưa hỗ trợ tự bổ sung bbox mới cho ID dạng `img:`, nên mục này mới `escalate`, chưa tính là correction.

**Failure mode 2 — Duplicate đối xứng:** Với cặp `ann_032`–`ann_d02` và `ann_058`–`ann_d00`, hệ thống có thể đẩy **cả bbox cần giữ lẫn bbox cần bỏ** vào top-B. Reviewer phải quyết định thủ công nhãn nào giữ lại. Điều này làm giảm hiệu quả ngân sách review.

**Failure mode 3 — Tin detector quá mức:** Prediction confidence cao vẫn có thể sai class; khi model sai, `class_disagreement` có thể tạo false positive. Cần xác nhận bằng quan sát và guideline, không tự động đổi nhãn.

## 07 · Human review & decision

Đã dùng `out/poc/review_queue.csv` top **B=10**, contact sheet HTML offline và file reviewer xuất `out/poc/review_queue_reviewed.csv`. Người kiểm tra chọn các quyết định `approve`, `edit`, `reject`, `escalate`; với `edit` truyền JSON patch như `{"class":"pedestrian"}`, với `reject` loại bỏ annotation trùng.

Pipeline giữ nguyên fixture nguồn, tạo `raw_annotations.csv`, `clean_annotations.csv`, `changed_labels.csv`; ghi sự kiện kèm reviewer, lý do và before/after vào `audit_log.jsonl`. Lần kiểm tra được chia sẻ xác nhận chính xác sáu hàng thay đổi:

`ann_096 (edit)`, `ann_134 (edit)`, `ann_d02 (reject)`, `ann_d00 (reject)`, `ann_186 (reject)`, `ann_109 (edit)`.

**Risk gate:** `decision.json` giữ `HOLD` nếu chưa có phê duyệt độc lập; `reason_code` tùy trạng thái review (`AWAITING_HUMAN_REVIEW`, `CORRECTIONS_REQUIRE_VERIFICATION` hoặc `AWAITING_RELEASE_APPROVAL`). Đây là chính sách PoC an toàn, không phải một chứng nhận pháp lý. Log kiểu append-only có nguy cơ trùng sự kiện khi chạy lại cùng quyết định; cần quản lý run ID/idempotency trong phiên bản tiếp theo.

## 08 · Reproduce & tests

Môi trường thực hiện: Windows, Git Bash, Python trong `.venv`; chạy offline (`seed=42`). Python version, CPU cụ thể và Git commit SHA **không có trong log đã chia sẻ** trong log cung cấp; cần lấy từ `out/poc/run_info.json` / `git rev-parse HEAD` nếu muốn ghi chính xác.

```bash
.venv/Scripts/python.exe -m tools.preflight
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m src.main --config configs/lab.yaml --track t11 --output out/poc --run-name poc --offline --seed 42
```

**Kiểm thử thực tế:** lần cuối `pytest -q` đạt **100% tiến độ, không có `F`/FAILED**; một số test `s` (skipped) do điều kiện dữ liệu/chấm GT. Pipeline cuối trả **`status=0`, `runtime=0.545s`**. Đã xử lý test template cũ thử chạy T02 bằng cách để track chưa implement trả mã 3 rõ ràng. Các test IoU gồm bbox trùng khít và bbox không giao nhau đã được bổ sung theo quá trình thực hiện; cần kiểm tra chúng đã nằm trong commit cuối.

## 09 · Limitations & ethics

- **Không có GT chính thức**: không kết luận Recall@B, Precision@B, cải thiện so với baseline hay sai số hiệu chỉnh.
- **Model disagreement ≠ nhãn sai**: confidence của prediction không thay cho kiểm tra của con người.
- **Chưa hỗ trợ thêm bbox missing**, chưa hiển thị bbox trực tiếp trên contact sheet và chưa kiểm tra hết các trường hợp bbox lệch/ra ngoài biên.
- **Review budget hạn chế**: các cặp duplicate tạo hai item nghi lỗi cho cùng một vấn đề, làm tốn lượt kiểm tra.
- **Audit/idempotency**: chạy nhiều lần cùng reviewer CSV có thể tạo log trùng; phải lưu bằng chứng và không sửa/xóa lịch sử một cách tùy tiện.
- **Quyền riêng tư & license**: thực hành trên fixture synthetic; không commit ảnh người thật, biển số thật, secret hoặc dữ liệu không có quyền sử dụng. Không tuyên bố tự động đáp ứng GDPR hay luật Việt Nam.

Hướng cải tiến: vẽ bbox annotation/prediction trực tiếp trên contact sheet; đưa reviewer vào quy trình thêm bbox cho missing; chuẩn hóa scoring theo class và confidence; gom cặp duplicate thành một review case; bổ sung kiểm tra biên ảnh và test end-to-end; đánh giá thực nghiệm trên heldout khi có overlay giảng viên.

## 10 · Đóng góp cá nhân

**Lê Việt Long (MSSV: 2A202603043)** thực hiện cấu hình T11, cài đặt heuristic scoring và pipeline, vận hành random baseline, review 10 mục, áp dụng 6 chỉnh sửa (3 edit, 3 reject), kiểm thử và viết báo cáo. Đây là bài thực hành cá nhân; không có thành viên nhóm khác.

Bằng chứng Git: đối chiếu tác giả và commit SHA bằng `git shortlog -sne --all` và `git log -1 --format=%h` sau khi commit. Không khai báo commit chưa tạo.

## 11 · References

| Nguồn | Vai trò |
|---|---|
| [README repo Day 06](https://github.com/VinUni-AI20k/K5-Day6-L2-DataGovernanceAndPrivacy) | Contract, rubric, nguyên tắc offline/GT guard và yêu cầu Human Review |
| [T11 challenge](https://github.com/VinUni-AI20k/K5-Day6-L2-DataGovernanceAndPrivacy/blob/main/docs/tracks/T11.md) | Schema, lỗi cần phát hiện, baseline, metric và các failure mode |
| [Evaluator `tracks.py`](https://github.com/VinUni-AI20k/K5-Day6-L2-DataGovernanceAndPrivacy/blob/main/src/metrics/tracks.py) | Cách tính Error Recall@B, Precision@B và metric theo loại lỗi |
| [Review helper](https://github.com/VinUni-AI20k/K5-Day6-L2-DataGovernanceAndPrivacy/blob/main/src/common/review.py) | Review queue, reviewer decisions, override và audit log |

---

## Bảng 3 · Checklist chốt khi nộp

- [x] Đã chọn T11; baseline và PoC tạo được `ranking.csv`.
- [x] Pipeline T11 chạy offline, `seed=42`, `status=0`.
- [x] Review top 10 và ghi nhận 6 chỉnh sửa trong `changed_labels.csv`.
- [x] `pytest -q` lần cuối không có FAILED.
- [ ] Kiểm tra URL repo sau push và tạo tag nếu coach yêu cầu.
- [ ] Sao lưu bằng chứng review/audit sang thư mục không bị `.gitignore` loại trừ và push repo.
- [ ] Nhờ giảng viên cung cấp/chạy overlay GT để tạo metrics và bảng so sánh chính thức; không tự ghi số liệu.
