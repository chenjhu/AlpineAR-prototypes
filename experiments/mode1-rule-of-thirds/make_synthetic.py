"""Generate fake top-view scenes (phone looking straight down on two stones)
to test the pipeline before we have real photos. Writes samples/*.png.

    python make_synthetic.py
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

W, H = 960, 720
CENTER = np.array([W / 2, H / 2], np.float32)


def _ground(rng) -> np.ndarray:
    base = np.full((H, W, 3), (150, 170, 182), np.float32)       # beige gravel (BGR)
    base += rng.normal(0, 14, (H, W, 1))
    speckle = cv2.GaussianBlur(rng.normal(0, 30, (H, W)).astype(np.float32), (0, 0), 1.5)
    base += speckle[..., None]
    shade = np.linspace(0.85, 1.1, W, dtype=np.float32)[None, :, None]  # uneven light
    return base * shade


def _blob(rng, a0, a1, half_depth, b_mid=0.0, n=48) -> np.ndarray:
    """Rounded, slightly irregular stone outline in wall coords (a along, b across)."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    p = 4.0                                            # superellipse: rounded box
    r = 1 / (np.abs(c) ** p + np.abs(s) ** p) ** (1 / p)
    noise = np.convolve(np.tile(rng.normal(0, 0.05, n), 3), np.ones(5) / 5, "same")[n:2 * n]
    r = r * (1 + noise)
    half_len = (a1 - a0) / 2
    return np.stack([(a0 + a1) / 2 + half_len * r * c, b_mid + half_depth * r * s], axis=1)


def _to_image(local: np.ndarray, angle_deg: float) -> np.ndarray:
    th = np.radians(angle_deg)
    u = np.array([np.cos(th), np.sin(th)], np.float32)
    n = np.array([-u[1], u[0]], np.float32)
    return CENTER + local[:, :1] * u + local[:, 1:] * n


def _paint_stone(img, poly, color, rng, shadow=6) -> None:
    pts = np.round(poly).astype(np.int32)
    # soft drop shadow (light from the top left)
    sh = np.zeros(img.shape[:2], np.float32)
    cv2.fillPoly(sh, [pts + shadow], 1.0, cv2.LINE_AA)
    img *= 1 - 0.35 * cv2.GaussianBlur(sh, (0, 0), shadow)[..., None]
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(mask, [pts], 255, cv2.LINE_AA)
    tex = cv2.GaussianBlur(rng.normal(0, 25, img.shape[:2]).astype(np.float32), (0, 0), 3)
    stone = np.array(color, np.float32) + tex[..., None]
    m = (mask.astype(np.float32) / 255)[..., None]
    img[:] = img * (1 - m) + stone * m
    cv2.polylines(img, [pts], True, (60, 65, 70), 2, cv2.LINE_AA)


def make_scene(seed=0, gap=14, angle=0.0, placed=None, left_len=260, right_len=220,
               left_depth=170, right_depth=150):
    """Returns (bgr image, ground-truth polygons [stone 1, stone 2, (placed)]).
    `placed` = (a0, a1) along the wall, measured from the wall centre, puts a
    third stone on top of the two. Same seed = same base stones, so a scene
    with and without `placed` is a before/after pair from a fixed phone."""
    rng = np.random.default_rng(seed)
    img = _ground(rng)
    a0 = -(left_len + gap + right_len) / 2
    polys = [
        _to_image(_blob(rng, a0, a0 + left_len, left_depth / 2), angle),
        _to_image(_blob(rng, a0 + left_len + gap, a0 + left_len + gap + right_len,
                        right_depth / 2), angle),
    ]
    _paint_stone(img, polys[0], (120, 118, 112), rng)
    _paint_stone(img, polys[1], (100, 110, 125), rng)
    rng_top = np.random.default_rng(seed + 1000)  # placed stone must not change the base
    if placed is not None:
        polys.append(_to_image(_blob(rng_top, placed[0], placed[1], 70), angle))
        _paint_stone(img, polys[2], (125, 140, 135), rng_top, shadow=12)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    return np.clip(img, 0, 255).astype(np.uint8), polys


def main() -> int:
    out = Path("samples")
    out.mkdir(exist_ok=True)
    # stones 1/2 span [-247, 13] and [27, 247] along the wall:
    # must = [-74, 100], allowed = [-160, 174]
    scenes = {
        "scene_two_stones": make_scene(0),
        "scene_touching": make_scene(1, gap=0),
        "scene_rotated": make_scene(2, angle=-35, left_len=300, right_len=180),
        "scene_after_good": make_scene(0, placed=(-110, 120)),
        "scene_after_bad": make_scene(0, placed=(30, 240)),
    }
    for name, (img, _) in scenes.items():
        cv2.imwrite(str(out / f"{name}.png"), img)
    print(f"wrote {len(scenes)} images to {out}/ (scene_two_stones = 'before' "
          "for both scene_after_* images)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
