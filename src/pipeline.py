"""YOUR PoC PIPELINE — this is the file your group owns.
Lab contract = 5 automated steps, run by `python -m src.main ...`:
    01 load      input + provenance check (manifest.csv)
    02 process   your algorithm / model (the research part)
    03 rank      prioritise for a fixed review budget B
    04 review    human-in-the-loop: queue -> reviewer decisions -> overrides + audit log
    05 decide    GO / HOLD / REWORK (or track equivalent) with reason_code + owner, write outputs

Required output: out/<pred_file> with the columns listed for your track in
docs/tracks/TXX.md (also in src/metrics/tracks.py::TRACKS). Then evaluate with
    python -m src.evaluate --track tXX --pred out/<pred_file>

Rules: never read fixtures/*/gt/ here (the GT guard will stop you); seed everything via ctx.rng;
no network calls; fail loudly on missing models instead of downloading.
See src/examples/random_baseline.py for a minimal end-to-end wiring example.
"""
from __future__ import annotations
import json
import pandas as pd

from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.manifest import verify_manifest
from .common.review import load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track


# ---------------------------------------------------------------- 01 load

def load(ctx: RunContext) -> dict:

    if ctx.track != "t11":
        raise NotImplementedError(
            f"Pipeline only implements T11, got {ctx.track}"
        )

    manifest = ctx.input_dir / "manifest.csv"
    manifest = ctx.input_dir / "manifest.csv"

    # 1. Kiểm tra tính toàn vẹn dữ liệu
    problems = verify_manifest(manifest)

    if problems:
        ctx.audit.log(
            actor="pipeline",
            action="provenance_problems",
            item_id=str(manifest),
            after=problems[:20]
        )

        if ctx.config.get("strict_provenance", True):
            raise ValueError(
                f"Provenance check failed: {problems[:3]}"
            )

    # 2. Đọc dữ liệu được phép sử dụng
    annotations = pd.read_csv(
        ctx.input_dir / "annotations.csv"
    )

    predictions = pd.read_csv(
        ctx.input_dir / "model_predictions.csv"
    )

    images = pd.read_csv(
        ctx.input_dir / "images.csv"
    )

    # 3. Trả dữ liệu cho process()
    return {
        "annotations": annotations,
        "predictions": predictions,
        "images": images
    }

def calculate_iou(a, b):
    # Bbox có dạng x, y, w, h
    ax1, ay1 = float(a["x"]), float(a["y"])
    ax2 = ax1 + float(a["w"])
    ay2 = ay1 + float(a["h"])

    bx1, by1 = float(b["x"]), float(b["y"])
    bx2 = bx1 + float(b["w"])
    by2 = by1 + float(b["h"])

    # Vùng giao nhau
    iw = max(0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0, min(ay2, by2) - max(ay1, by1))
    intersection = iw * ih

    # Diện tích hợp
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)

    union = area_a + area_b - intersection

    if union <= 0:
        return 0.0

    return intersection / union



# ---------------------------------------------------------------- 02 process

def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    annotations = data["annotations"]
    predictions = data["predictions"]
    images = data["images"]

    results = []

    # Mỗi annotation được kiểm tra riêng
    for _, ann in annotations.iterrows():
        same_image = predictions[
            predictions["image_id"] == ann["image_id"]
        ]

        best_iou = 0.0
        best_pred = None

        # Tìm prediction có IoU cao nhất
        for _, pred in same_image.iterrows():
            iou = calculate_iou(ann, pred)

            if iou > best_iou:
                best_iou = iou
                best_pred = pred

        score = 0.0
        reasons = []

        # Trường hợp 1: class disagreement
        if best_pred is not None and best_iou >= 0.5:
            if ann["class"] != best_pred["class"]:
                confidence = float(best_pred["conf"])
                score = max(score, confidence)
                reasons.append("class_disagreement")

        # Trường hợp 2: annotation khó khớp prediction
        if best_iou < 0.3:
            score = max(score, 0.65)
            reasons.append("low_prediction_match")

        # Trường hợp 3: duplicate annotation
        same_annotations = annotations[
            (annotations["image_id"] == ann["image_id"]) &
            (annotations["ann_id"] != ann["ann_id"])
        ]

        for _, other in same_annotations.iterrows():
            iou = calculate_iou(ann, other)

            if iou > 0.85 and ann["class"] == other["class"]:
                score = max(score, 0.9)
                reasons.append("possible_duplicate")
                break

        results.append({
            "item_id": str(ann["ann_id"]),
            "score": score,
            "reason": ";".join(reasons) or "no_obvious_issue",
            "image_id": ann["image_id"]
        })

    # Trường hợp 4: ảnh có khả năng thiếu annotation
    for _, img in images.iterrows():
        image_id = img["image_id"]
        img_predictions = predictions[
            predictions["image_id"] == image_id
        ]
        img_annotations = annotations[
            annotations["image_id"] == image_id
        ]

        missing_score = 0.0

        for _, pred in img_predictions.iterrows():
            confidence = float(pred["conf"])

            if confidence < 0.75:
                continue

            best_match = 0.0

            for _, ann in img_annotations.iterrows():
                iou = calculate_iou(pred, ann)
                best_match = max(best_match, iou)

            if best_match < 0.3:
                missing_score = max(missing_score, confidence)

        results.append({
            "item_id": f"img:{image_id}",
            "score": missing_score,
            "reason": (
                "possible_missing_annotation"
                if missing_score > 0
                else "no_obvious_issue"
            ),
            "image_id": image_id
        })

    return pd.DataFrame(results)



# ---------------------------------------------------------------- 03 rank

def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    from .common.contact_sheet import render_contact_sheet

    # Budget mặc định từ t11.yaml
    budget = int(ctx.param("budget", 10))

    # Bổ sung đường dẫn ảnh để reviewer có thể xem
    images = pd.read_csv(ctx.input_dir / "images.csv")

    scored_with_images = scored.merge(
        images[["image_id", "path"]],
        on="image_id",
        how="left"
    )

    # Xếp theo score giảm dần, chọn top-B
    queue = make_review_queue(
        scored_with_images,
        id_col="item_id",
        score_col="score",
        budget=budget,
        reason_col="reason",
        evidence_col="path"
    )

    write_review_queue(
        queue,
        ctx.out("review_queue.csv")
    )

    # Tạo giao diện review HTML
    render_contact_sheet(
        queue,
        ctx.out("contact_sheet.html"),
        image_root=ctx.input_dir,
        title="T11 Label Error Review"
    )

    return queue



# ---------------------------------------------------------------- 04 review

def review(ctx: RunContext, scored: pd.DataFrame,
           queue: pd.DataFrame) -> pd.DataFrame:

    raw = pd.read_csv(ctx.input_dir / "annotations.csv")

    # Luôn lưu dữ liệu gốc, không sửa fixtures
    raw.to_csv(ctx.out("raw_annotations.csv"), index=False)
    cleaned = raw.copy()

    reviewed_path = (
        ctx.output_dir / "review_queue_reviewed.csv"
    )

    changes = []
    reviewed_count = 0

    if reviewed_path.exists():
        reviewed = load_review_decisions(reviewed_path)
        reviewed_count = len(reviewed)

        for _, r in reviewed.iterrows():
            item_id = str(r["item_id"])
            action = str(r["reviewer_decision"])
            reviewer = str(r["reviewer"])
            note = str(r["review_note"])
            value = str(r["override_value"]).strip()

            # img:<id> là nghi vấn thiếu nhãn.
            # Không được tự tạo bbox khi chưa có tọa độ.
            if item_id.startswith("img:"):
                ctx.audit.log(
                    actor=reviewer,
                    action=action,
                    item_id=item_id,
                    reason=note
                )
                continue

            mask = cleaned["ann_id"].astype(str) == item_id

            if not mask.any():
                raise ValueError(f"Unknown ann_id: {item_id}")

            before = cleaned.loc[mask].iloc[0].to_dict()

            if action == "edit":
                if not value:
                    raise ValueError(
                        f"{item_id}: edit requires override_value"
                    )

                try:
                    patch = json.loads(value)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"{item_id}: invalid JSON override"
                    ) from e

                allowed = {"class", "x", "y", "w", "h"}

                if (
                    not isinstance(patch, dict)
                    or not patch
                    or set(patch) - allowed
                ):
                    raise ValueError(
                        f"{item_id}: invalid edit fields"
                    )

                if "class" in patch:
                    if not isinstance(patch["class"], str) \
                            or not patch["class"].strip():
                        raise ValueError(
                            f"{item_id}: invalid class"
                        )

                for col in ("x", "y", "w", "h"):
                    if col in patch:
                        try:
                            patch[col] = float(patch[col])
                        except (TypeError, ValueError) as e:
                            raise ValueError(
                                f"{item_id}: invalid {col}"
                            ) from e

                        import math
                        if not math.isfinite(patch[col]):
                            raise ValueError(
                                f"{item_id}: non-finite {col}"
                            )

                candidate = before.copy()
                candidate.update(patch)

                if candidate["w"] <= 0 or candidate["h"] <= 0:
                    raise ValueError(
                        f"{item_id}: invalid bbox size"
                    )

                for col, new_value in patch.items():
                    cleaned.loc[mask, col] = new_value

                after = cleaned.loc[mask].iloc[0].to_dict()

            elif action == "reject":
                # Reviewer xác nhận bbox không hợp lệ
                cleaned = cleaned.loc[~mask].copy()
                after = None

            else:
                ctx.audit.log(
                    actor=reviewer,
                    action=action,
                    item_id=item_id,
                    reason=note
                )
                continue

            # Lưu before/after và lý do
            changes.append({
                "item_id": item_id,
                "reviewer": reviewer,
                "action": action,
                "before": json.dumps(
                    before, ensure_ascii=False
                ),
                "after": json.dumps(
                    after, ensure_ascii=False
                ),
                "reason": note
            })

            ctx.audit.log(
                actor=reviewer,
                action=f"annotation_{action}",
                item_id=item_id,
                before=before,
                after=after,
                reason=note
            )

    cleaned.to_csv(
        ctx.out("clean_annotations.csv"),
        index=False
    )

    pd.DataFrame(
        changes,
        columns=[
            "item_id", "reviewer", "action",
            "before", "after", "reason"
        ]
    ).to_csv(
        ctx.out("changed_labels.csv"),
        index=False
    )

    ctx.stats["n_reviewed"] = reviewed_count
    ctx.stats["n_changed"] = len(changes)

    return scored



# ---------------------------------------------------------------- 05 decide

def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    n_reviewed = ctx.stats.get("n_reviewed", 0)
    n_changed = ctx.stats.get("n_changed", 0)

    # Chính sách PoC: chưa tự động phát hành dữ liệu
    # nếu chưa được chủ dữ liệu phê duyệt cuối cùng.
    status = "HOLD"

    if n_reviewed == 0:
        reason_code = "AWAITING_HUMAN_REVIEW"
        reason = "Review queue has not been reviewed."

    elif n_changed > 0:
        reason_code = "CORRECTIONS_REQUIRE_VERIFICATION"
        reason = (
            f"{n_changed} label corrections require "
            "independent verification before release."
        )

    else:
        reason_code = "AWAITING_RELEASE_APPROVAL"
        reason = (
            "Review completed; final release approval "
            "is still required."
        )

    return Decision(
        status=status,
        reason_code=reason_code,
        reason=reason,
        owner=ctx.config["owner"],
        scope=ctx.track,
        evidence=[
            str(ctx.out("ranking.csv")),
            str(ctx.out("changed_labels.csv"))
        ],
        metrics={
            "n_reviewed": n_reviewed,
            "n_changed": n_changed
        }
    )



def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    final[spec.pred_columns + [c for c in final.columns if c not in spec.pred_columns]].to_csv(ctx.out(spec.pred_file), index=False)
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
