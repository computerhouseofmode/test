"""実光線追跡（ベクトル化）。

各面の局所座標は頂点を原点とし、z を光軸とする（偏心・傾きは未対応）。
面形状: z = c r^2 / (1 + sqrt(1 - (1+k) c^2 r^2)) + A4 r^4 + A6 r^6 + ...
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .paraxial import FirstOrder, first_order
from .system import OpticalSystem, Surface


def sag(s: Surface, x, y):
    c, k = s.curvature, s.conic
    r2 = x * x + y * y
    arg = 1.0 - (1.0 + k) * c * c * r2
    z = c * r2 / (1.0 + np.sqrt(np.maximum(arg, 0.0)))
    for i, a in enumerate(s.aspheric):
        z = z + a * r2 ** (i + 2)
    return z


def _sag_slope_factor(s: Surface, r2):
    """dz/dx = x * g,  dz/dy = y * g  となる g を返す。"""
    c, k = s.curvature, s.conic
    arg = 1.0 - (1.0 + k) * c * c * r2
    g = c / np.sqrt(np.maximum(arg, 1e-300))
    for i, a in enumerate(s.aspheric):
        g = g + a * 2 * (i + 2) * r2 ** (i + 1)
    return g


def intersect(s: Surface, P: np.ndarray, D: np.ndarray):
    """光線 P + tD と面 s の交点までの距離 t と有効フラグ。"""
    c, k = s.curvature, s.conic
    px, py, pz = P[:, 0], P[:, 1], P[:, 2]
    dx, dy, dz = D[:, 0], D[:, 1], D[:, 2]
    if c == 0.0:
        t = -pz / dz
        ok = np.isfinite(t)
    else:
        a = c * (dx * dx + dy * dy + (1 + k) * dz * dz)
        b = c * (px * dx + py * dy + (1 + k) * pz * dz) - dz
        cc = c * (px * px + py * py + (1 + k) * pz * pz) - 2 * pz
        disc = b * b - a * cc
        ok = disc >= 0
        sq = np.sqrt(np.maximum(disc, 0.0))
        t = -cc / (b + np.where(b >= 0, sq, -sq))
    if s.aspheric:
        for _ in range(20):
            q = P + t[:, None] * D
            r2 = q[:, 0] ** 2 + q[:, 1] ** 2
            g = _sag_slope_factor(s, r2)
            f = q[:, 2] - sag(s, q[:, 0], q[:, 1])
            dfdt = dz - g * (q[:, 0] * dx + q[:, 1] * dy)
            step = f / dfdt
            t = t - step
            if np.nanmax(np.abs(step)) < 1e-13:
                break
    q = P + t[:, None] * D
    r2 = q[:, 0] ** 2 + q[:, 1] ** 2
    if c != 0.0:
        ok &= (1.0 - (1.0 + k) * c * c * r2) >= 0
    return t, ok & np.isfinite(t)


def normal(s: Surface, Q: np.ndarray) -> np.ndarray:
    r2 = Q[:, 0] ** 2 + Q[:, 1] ** 2
    g = _sag_slope_factor(s, r2)
    N = np.stack([-Q[:, 0] * g, -Q[:, 1] * g, np.ones_like(g)], axis=1)
    return N / np.linalg.norm(N, axis=1, keepdims=True)


def refract(D: np.ndarray, N: np.ndarray, n1: float, n2: float):
    cos_i = np.einsum("ij,ij->i", D, N)
    N = np.where(cos_i[:, None] < 0, -N, N)
    cos_i = np.abs(cos_i)
    mu = n1 / n2
    k = 1.0 - mu * mu * (1.0 - cos_i * cos_i)
    ok = k >= 0
    D2 = mu * D + (np.sqrt(np.maximum(k, 0.0)) - mu * cos_i)[:, None] * N
    return D2, ok


@dataclass
class TraceResult:
    P: np.ndarray            # 像面上の交点（像面局所座標）
    D: np.ndarray            # 像空間での方向余弦
    opl: np.ndarray          # 光路長 [mm]
    valid: np.ndarray        # ケラレ・全反射・面外れのない光線
    n_image: float
    history: list[np.ndarray] = field(default_factory=list)  # 各面の交点（record=True のとき）

    @property
    def x(self):
        return np.where(self.valid, self.P[:, 0], np.nan)

    @property
    def y(self):
        return np.where(self.valid, self.P[:, 1], np.nan)


def trace(system: OpticalSystem, P0: np.ndarray, D0: np.ndarray, wl: float,
          clip: bool = True, record: bool = False) -> TraceResult:
    """面 1 局所座標で与えた光線 (P0, D0) を像面まで追跡する。"""
    P = np.array(P0, dtype=float, copy=True)
    D = np.array(D0, dtype=float, copy=True)
    npts = P.shape[0]
    opl = np.zeros(npts)
    valid = np.ones(npts, dtype=bool)
    n = system.index(0, wl)
    hist = []
    last = system.image_index
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        for j in range(1, last + 1):
            s = system.surfaces[j]
            t, ok = intersect(s, P, D)
            P = P + t[:, None] * D
            opl += n * t
            valid &= ok
            if clip and s.semi_diameter is not None and j != last:
                valid &= np.hypot(P[:, 0], P[:, 1]) <= s.semi_diameter * (1 + 1e-9)
            if record:
                hist.append(P.copy())
            if j == last:
                break
            n2 = system.index(j, wl)
            if n2 != n:
                D, ok = refract(D, normal(s, P), n, n2)
                valid &= ok
            n = n2
            P = P.copy()
            P[:, 2] -= s.thickness
    return TraceResult(P, D, opl, valid, n, hist)


# --------------------------------------------------------------------------
# 物体・瞳座標からの光線生成
# --------------------------------------------------------------------------
class RayGenerator:
    """正規化瞳座標 (px, py) と視野値から光線を生成する（近軸入射瞳を使用）。"""

    def __init__(self, system: OpticalSystem, fo: FirstOrder | None = None):
        self.system = system
        self.fo = fo or first_order(system)

    def rays(self, fy: float, px, py, fx: float = 0.0):
        sysm, fo = self.system, self.fo
        px = np.atleast_1d(np.asarray(px, dtype=float))
        py = np.atleast_1d(np.asarray(py, dtype=float))
        R, zep = fo.ep_radius, fo.ep_z
        pep = np.stack([px * R, py * R, np.full_like(px, zep)], axis=1)
        if sysm.infinite_object:
            d = np.array([-math.tan(math.radians(fx)), -math.tan(math.radians(fy)), 1.0])
            d /= np.linalg.norm(d)
            D = np.tile(d, (len(px), 1))
            # 入射瞳中心を通り光線に垂直な平面（等位相面）上に始点を置く
            center = np.array([0.0, 0.0, zep])
            t0 = -((pep - center) @ d)
            P = pep + t0[:, None] * d
        else:
            d0 = sysm.surfaces[0].thickness
            if sysm.field_type == "angle":
                hy = (d0 + zep) * math.tan(math.radians(fy))
                hx = (d0 + zep) * math.tan(math.radians(fx))
            else:
                hy, hx = fy, fx
            obj = np.array([hx, hy, -d0])
            D = pep - obj
            D /= np.linalg.norm(D, axis=1, keepdims=True)
            P = np.tile(obj, (len(px), 1))
        return P, D

    def trace(self, fy: float, px, py, wl: float, fx: float = 0.0, **kw) -> TraceResult:
        P, D = self.rays(fy, px, py, fx)
        return trace(self.system, P, D, wl, **kw)


def auto_semi_diameters(system: OpticalSystem, n_edge: int = 36) -> np.ndarray:
    """全視野・全波長の周辺光線から各面の有効半径を求める（固定値があればそれを使用）。"""
    gen = RayGenerator(system)
    th = np.linspace(0, 2 * np.pi, n_edge, endpoint=False)
    px, py = np.concatenate([[0.0], np.cos(th)]), np.concatenate([[0.0], np.sin(th)])
    sd = np.zeros(len(system.surfaces))
    for fy in system.fields:
        for wl in system.wavelengths:
            r = gen.trace(fy, px, py, wl, clip=False, record=True)
            for j, Q in enumerate(r.history, start=1):
                h = np.hypot(Q[r.valid, 0], Q[r.valid, 1])
                if h.size:
                    sd[j] = max(sd[j], float(h.max()))
    for j, s in enumerate(system.surfaces):
        if s.semi_diameter is not None:
            sd[j] = s.semi_diameter
    return sd
