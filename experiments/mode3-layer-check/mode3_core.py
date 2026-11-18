"""Mode 3 (3D controlling): compare a finished layer of stones with the
target truncated cone and find what sticks out.

The target is a truncated cone (the whole wall/tower), built in layers of
equal height. For the current layer k, a stone part is OK if it lies inside
the cone and below the layer's top plane z = (k + 1) * layer_height.
Everything else is excess (red in AR):

    above   the part above the top plane: the stone is too tall ("every layer
            has to be as flat as possible", p.32)
    outside the part outside the cone surface: the stone sticks out of the
            target shape

Pure Python (numpy + trimesh with the manifold boolean engine), so it runs
without Rhino. grasshopper/mode3_component.py does the same in Grasshopper.
Units: metres, z up, cone axis on the z axis through `center`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

ENGINE = "manifold"


@dataclass
class Target:
    r_bottom: float = 2.0       # radius at z = 0
    r_top: float = 1.4          # radius at z = height
    height: float = 2.4
    layer_height: float = 0.3
    center: tuple[float, float] = (0.0, 0.0)
    segments: int = 128         # facets of the cone mesh

    @property
    def layers(self) -> int:
        return int(round(self.height / self.layer_height))

    def radius_at(self, z) -> np.ndarray:
        return self.r_bottom + (self.r_top - self.r_bottom) * np.asarray(z) / self.height

    def layer_top(self, k: int) -> float:
        return (k + 1) * self.layer_height

    def cone_mesh(self) -> trimesh.Trimesh:
        """Closed truncated cone. The polygon is circumscribed (its flat sides
        touch the true circle), so faceting never cuts into the target."""
        n = self.segments
        scale = 1 / np.cos(np.pi / n)
        a = np.linspace(0, 2 * np.pi, n, endpoint=False)
        ring = np.stack([np.cos(a), np.sin(a)], axis=1)
        cx, cy = self.center
        bottom = np.c_[cx + ring[:, 0] * self.r_bottom * scale,
                       cy + ring[:, 1] * self.r_bottom * scale, np.zeros(n)]
        top = np.c_[cx + ring[:, 0] * self.r_top * scale,
                    cy + ring[:, 1] * self.r_top * scale, np.full(n, self.height)]
        v = np.vstack([bottom, top, [[cx, cy, 0]], [[cx, cy, self.height]]])
        f = []
        for i in range(n):
            j = (i + 1) % n
            f += [[i, j, n + j], [i, n + j, n + i],          # side
                  [2 * n, j, i], [2 * n + 1, n + i, n + j]]  # bottom, top caps
        mesh = trimesh.Trimesh(v, np.array(f), process=True)
        mesh.fix_normals()
        return mesh

    def below(self, z: float) -> trimesh.Trimesh:
        """A big box holding everything below the plane at height z."""
        size = 4 * max(self.r_bottom, self.r_top) + 10
        box = trimesh.creation.box((size, size, size))
        box.apply_translation((self.center[0], self.center[1], z - size / 2))
        return box


@dataclass
class StoneResult:
    name: str
    stone: trimesh.Trimesh
    ok: trimesh.Trimesh | None
    above: trimesh.Trimesh | None
    outside: trimesh.Trimesh | None
    above_volume: float
    outside_volume: float
    too_tall_by: float           # how far the stone rises above the top plane
    sticks_out_by: float         # max distance outside the cone surface
    section: list = field(default_factory=list)   # cut line(s) on the top plane
    tolerance: float = 0.01      # excess smaller than this is not worth a chisel

    @property
    def ok_flag(self) -> bool:
        return self.too_tall_by < self.tolerance and self.sticks_out_by < self.tolerance


def _nonempty(mesh) -> trimesh.Trimesh | None:
    return mesh if mesh is not None and len(mesh.faces) and mesh.volume > 1e-7 else None


def check_stone(name: str, stone: trimesh.Trimesh, target: Target, layer: int,
                tolerance: float = 0.01) -> StoneResult:
    z_top = target.layer_top(layer)
    cone = target.cone_mesh()
    below = target.below(z_top)

    inside_cone = stone.intersection(cone, engine=ENGINE)
    ok = _nonempty(inside_cone.intersection(below, engine=ENGINE))
    above = _nonempty(stone.difference(below, engine=ENGINE))
    below_part = stone.intersection(below, engine=ENGINE)
    outside = _nonempty(below_part.difference(cone, engine=ENGINE))

    v = stone.vertices
    radial = np.hypot(v[:, 0] - target.center[0], v[:, 1] - target.center[1])
    sticks_out = float(max(0.0, (radial - target.radius_at(np.clip(v[:, 2], 0, target.height))).max()))
    too_tall = float(max(0.0, v[:, 2].max() - z_top))

    section = []
    if above is not None:
        s = stone.section(plane_origin=(0, 0, z_top), plane_normal=(0, 0, 1))
        if s is not None:
            section = [np.asarray(e) for e in s.discrete]

    return StoneResult(name, stone, ok, above, outside,
                       above.volume if above is not None else 0.0,
                       outside.volume if outside is not None else 0.0,
                       too_tall, sticks_out, section, tolerance)


def virtual_layer(target: Target, layer: int, count: int | None = None, seed: int = 0,
                  tall: tuple[int, ...] = (), out: tuple[int, ...] = ()) -> list[tuple[str, trimesh.Trimesh]]:
    """A course of irregular stones along the cone's outer surface, for testing
    without real stones. Stones listed in `tall` are made too tall, stones in
    `out` stick out of the cone; the rest are placed correctly."""
    rng = np.random.default_rng(seed)
    z0 = layer * target.layer_height
    h = target.layer_height
    r_mid = float(target.radius_at(z0 + h / 2))
    length = 0.5                                      # along the wall
    if count is None:
        count = int(2 * np.pi * r_mid / (length + 0.015))
    stones = []
    for i in range(count):
        a = 2 * np.pi * (i + rng.uniform(-0.08, 0.08)) / count
        L = length * rng.uniform(0.9, 1.0)
        D = rng.uniform(0.34, 0.42)                    # into the wall
        H = h * (rng.uniform(1.35, 1.5) if i in tall else rng.uniform(0.82, 0.97))
        # random points in a rounded block, convex hull = an irregular stone
        p = rng.uniform(-0.5, 0.5, (40, 3)) * [L, D, H]
        p *= 1 - 0.1 * (np.abs(p) / [L / 2, D / 2, H / 2]).max(axis=1, keepdims=True) ** 3
        p = np.vstack([p, np.array([[sx, sy, sz] for sx in (-.45, .45) for sy in (-.45, .45)
                                    for sz in (-.5, .5)]) * [L, D, H]])   # keep it blocky
        p[:, 2] -= p[:, 2].min()                      # sit on the layer bottom
        stone = trimesh.convex.convex_hull(p)
        # outer face just inside the cone (small batter), or pushed outside
        outward = rng.uniform(0.06, 0.10) if i in out else -rng.uniform(0.015, 0.03)
        r_out = float(target.radius_at(z0 + H)) + outward
        radial = r_out - D / 2
        rot = trimesh.transformations.rotation_matrix(a + np.pi / 2, (0, 0, 1))
        stone.apply_transform(rot)
        stone.apply_translation((target.center[0] + radial * np.cos(a),
                                 target.center[1] + radial * np.sin(a), z0))
        stones.append((f"L{layer}-{i + 1:02d}", stone))
    return stones
