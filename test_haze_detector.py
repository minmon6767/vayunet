"""
Sanity checks for haze_detector.py. We generate synthetic images instead of
relying on sample photos, so these tests run anywhere with no fixture files
to keep in sync.
"""

import os
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from haze_detector import estimate_haze_score, haze_score_to_label


def _save_temp_image(array):
    path = tempfile.mktemp(suffix=".png")
    Image.fromarray(array.astype(np.uint8)).save(path)
    return path


def test_uniform_gray_image_reads_as_hazy():
    # A flat, low-contrast gray field is exactly what haze looks like: no
    # patch has a genuinely dark pixel anywhere.
    hazy = np.full((100, 100, 3), 180, dtype=np.uint8)
    path = _save_temp_image(hazy)
    try:
        score = estimate_haze_score(path)
        assert score > 0.3
    finally:
        os.remove(path)


def test_high_contrast_image_reads_as_clearer_than_flat_haze():
    # Checkerboard pattern gives every patch a genuinely dark pixel --
    # the dark-channel prior should read this as much clearer than the
    # flat gray "haze" image above.
    rng = np.random.default_rng(42)
    checkerboard = np.zeros((100, 100, 3), dtype=np.uint8)
    checkerboard[::10, :] = 255
    checkerboard[:, ::10] = 255

    flat = np.full((100, 100, 3), 180, dtype=np.uint8)

    path_checker = _save_temp_image(checkerboard)
    path_flat = _save_temp_image(flat)
    try:
        score_checker = estimate_haze_score(path_checker)
        score_flat = estimate_haze_score(path_flat)
        assert score_checker < score_flat
    finally:
        os.remove(path_checker)
        os.remove(path_flat)


def test_score_to_label_boundaries():
    assert haze_score_to_label(0.0) == "clear"
    assert haze_score_to_label(0.95) == "severe / visibility critical"


if __name__ == "__main__":
    test_uniform_gray_image_reads_as_hazy()
    test_high_contrast_image_reads_as_clearer_than_flat_haze()
    test_score_to_label_boundaries()
    print("all haze_detector tests passed")
