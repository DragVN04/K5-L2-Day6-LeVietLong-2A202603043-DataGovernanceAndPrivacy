
from src.pipeline import calculate_iou


def test_iou_identical_boxes():
    """Hai bbox giống nhau phải có IoU = 1."""
    a = {"x": 10, "y": 20, "w": 30, "h": 40}

    assert calculate_iou(a, a) == 1.0


def test_iou_non_overlapping_boxes():
    """Hai bbox không giao nhau phải có IoU = 0."""
    a = {"x": 0, "y": 0, "w": 10, "h": 10}
    b = {"x": 100, "y": 100, "w": 10, "h": 10}

    assert calculate_iou(a, b) == 0.0
