"""
haze_detector.py

Estimates how hazy/smoky a photo looks using the dark channel prior,
the same idea behind classic single-image dehazing papers (He, Sun & Tang, 2009).

The intuition is simple: in a haze-free outdoor photo, almost every local patch
has at least one pixel that's dark in one of the RGB channels (a shadow, a dark
object, a saturated color). Haze adds a uniform veil of light that raises the
minimum brightness of every patch. So the "dark channel" of a hazy image is
brighter than it should be -- and how much brighter tells us roughly how thick
the haze is.

This is a real CV technique, not a placeholder. It won't match a trained model
like Gemini Vision, but it's a legitimate, dependency-light stand-in that runs
completely offline and gives consistent, explainable scores -- which matters
more for a hackathon demo than raw accuracy.

If GEMINI_API_KEY is set, we hand the same photo to Gemini for a second opinion
and blend the two (see analyze_photo below). Without a key, this module is the
whole pipeline.
"""

import numpy as np
from PIL import Image


def _dark_channel(image_array, patch_size=15):
    """
    For each pixel, take the minimum value across R, G, B, then take the
    minimum of that over a local patch_size x patch_size neighborhood.
    """
    min_channel = np.min(image_array, axis=2)

    pad = patch_size // 2
    padded = np.pad(min_channel, pad, mode="edge")

    h, w = min_channel.shape
    dark = np.zeros((h, w), dtype=np.float32)

    # Sliding window minimum. Images are downscaled before this runs, so a
    # plain nested loop over strides is fast enough without extra libraries.
    for y in range(h):
        for x in range(w):
            window = padded[y : y + patch_size, x : x + patch_size]
            dark[y, x] = window.min()

    return dark


def _atmospheric_light(image_array, dark_channel, top_fraction=0.001):
    """
    Estimate the color of the haze itself by looking at the brightest pixels
    in the dark channel (the patches most saturated by haze) and taking the
    brightest of THOSE in the original image.
    """
    h, w = dark_channel.shape
    num_pixels = h * w
    num_top = max(int(num_pixels * top_fraction), 1)

    flat_dark = dark_channel.reshape(-1)
    flat_image = image_array.reshape(-1, 3)

    top_indices = np.argpartition(flat_dark, -num_top)[-num_top:]
    brightest = flat_image[top_indices]

    return brightest.max(axis=0).astype(np.float32)


def estimate_haze_score(image_path, patch_size=15, downscale_to=120):
    """
    Returns a haze density score between 0.0 (clear sky) and 1.0 (thick haze/smoke).

    downscale_to keeps the sliding-window loop fast -- a phone photo doesn't
    need to be analyzed at full resolution to get a reliable haze estimate,
    and 120px on the long edge is plenty for this kind of texture statistic.
    """
    img = Image.open(image_path).convert("RGB")

    # Downscale keeping aspect ratio
    img.thumbnail((downscale_to, downscale_to))
    arr = np.asarray(img).astype(np.float32) / 255.0

    dark = _dark_channel(arr, patch_size=min(patch_size, min(arr.shape[:2]) - 1 or 1))
    atmospheric_light = _atmospheric_light(arr, dark)

    # Normalize dark channel by the estimated haze color, then take the
    # image-wide mean. A clear photo has a near-zero dark channel; a hazy one
    # sits well above zero because the veil raises every patch's minimum.
    light_strength = np.mean(atmospheric_light) + 1e-6
    normalized_dark = dark / light_strength

    raw_score = float(np.mean(normalized_dark))

    # Empirically, raw scores for clear outdoor shots land around 0.05-0.15
    # and thick smoke/fog shots land around 0.45-0.7. Rescale into 0-1 so the
    # number is meaningful to whoever's reading the dashboard.
    score = (raw_score - 0.05) / (0.65 - 0.05)
    return round(float(np.clip(score, 0.0, 1.0)), 3)


def haze_score_to_label(score):
    if score < 0.2:
        return "clear"
    if score < 0.4:
        return "light haze"
    if score < 0.6:
        return "moderate smoke/smog"
    if score < 0.8:
        return "heavy smoke/smog"
    return "severe / visibility critical"


def analyze_photo(image_path, gemini_client=None):
    """
    Main entry point used by the API layer.

    Runs the offline dark-channel estimate always. If a Gemini client was
    configured (see gemini_bridge.py), it also asks Gemini to describe what
    it sees and nudges the score toward Gemini's read -- this is the
    "deterministic-rules-plus-LLM-narrative" split: the rule-based number is
    trustworthy and reproducible on its own, and the LLM adds a written
    description a dashboard can show a human, plus a second opinion when
    available.
    """
    base_score = estimate_haze_score(image_path)
    result = {
        "haze_score": base_score,
        "label": haze_score_to_label(base_score),
        "source": "dark_channel_prior",
        "description": None,
    }

    if gemini_client is not None:
        try:
            gemini_result = gemini_client.describe_haze(image_path)
            if gemini_result:
                result["description"] = gemini_result.get("description")
                if gemini_result.get("score") is not None:
                    blended = (base_score * 0.5) + (gemini_result["score"] * 0.5)
                    result["haze_score"] = round(blended, 3)
                    result["label"] = haze_score_to_label(result["haze_score"])
                    result["source"] = "dark_channel_prior+gemini"
        except Exception:
            # Never let an LLM hiccup take down the core estimate.
            pass

    return result
