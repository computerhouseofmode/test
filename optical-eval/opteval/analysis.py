"""像性能評価: スポット、収差曲線、波面収差、像面湾曲・歪曲、PSF、MTF。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .paraxial import FirstOrder, chief_ray_start, first_order, trace_paraxial
from .raytrace import RayGenerator, TraceResult
from .system import OpticalSystem


class Evaluator:
    """1 つの光学系に対する評価をまとめたクラス（近軸量をキャッシュ）。"""

    def __init__(self, system: OpticalSystem):
        self.system = system
        self.fo: FirstOrder = first_order(system)
        self.gen = RayGenerator(system, self.fo)
        self._chief_cache: dict[tuple[float, float], TraceResult] = {}

    # --- 基本 --------------------------------------------------------------
    def chief(self, fy: float, wl: float | None = None) -> TraceResult:
        wl = self.system.primary_wavelength if wl is None else wl
        key = (fy, wl)
        if key not in self._chief_cache:
            self._chief_cache[key] = self.gen.trace(fy, 0.0, 0.0, wl)
        return self._chief_cache[key]

    def trace(self, fy, px, py, wl, **kw) -> TraceResult:
        return self.gen.trace(fy, px, py, wl, **kw)

    def opd(self, fy: float, px, py, wl: float) -> tuple[np.ndarray, np.ndarray]:
        """主波長の主光線像点を中心とする参照球に対する OPD [waves]。

        正の値は参照球より波面が進んでいる（光路が短い）ことを表す。
        """
        ref = self.chief(fy)                  # 参照点は主波長の主光線
        own = self.chief(fy, wl)              # 位相基準は同じ波長の主光線
        r = self.trace(fy, px, py, wl)
        Q = ref.P[0]
        E = self._xp_point(ref)
        R = np.linalg.norm(Q - E)

        def opl_to_sphere(tr: TraceResult):
            v = tr.P - Q
            b = np.einsum("ij,ij->i", v, tr.D)
            c = np.einsum("ij,ij->i", v, v) - R * R
            s = -b - np.sqrt(np.maximum(b * b - c, 0.0))
            return tr.opl + tr.n_image * s

        w = (opl_to_sphere(own)[0] - opl_to_sphere(r)) / (wl * 1e-3)
        return np.where(r.valid, w, np.nan), r.valid

    def _xp_point(self, chief: TraceResult) -> np.ndarray:
        """主光線と射出瞳面の交点（像面局所座標）。"""
        zxp = self.fo.xp_z
        if not math.isfinite(zxp):
            zxp = -1e6
        P, D = chief.P[0], chief.D[0]
        return P + D * (zxp - P[2]) / D[2]


# --------------------------------------------------------------------------
# 瞳サンプリング
# --------------------------------------------------------------------------
def hexapolar(rings: int = 8) -> tuple[np.ndarray, np.ndarray]:
    px, py = [0.0], [0.0]
    for i in range(1, rings + 1):
        r = i / rings
        th = np.linspace(0, 2 * np.pi, 6 * i, endpoint=False)
        px.extend(r * np.sin(th))
        py.extend(r * np.cos(th))
    return np.array(px), np.array(py)


def square_grid(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    t = np.linspace(-1, 1, n)
    px, py = np.meshgrid(t, t)
    mask = px**2 + py**2 <= 1.0 + 1e-12
    return px, py, mask


# --------------------------------------------------------------------------
# スポットダイアグラム
# --------------------------------------------------------------------------
@dataclass
class SpotResult:
    field: float
    x: list[np.ndarray]           # 波長ごとの x（参照点からの相対値）[mm]
    y: list[np.ndarray]
    ref: tuple[float, float]      # 参照点（主波長主光線の像点）
    rms: float                    # 重心基準 RMS 半径（多色, 重み付き）[mm]
    geo: float                    # 重心基準 最大半径 [mm]
    rms_per_wl: list[float]
    centroid: tuple[float, float]  # 参照点からの重心ずれ


def spot(ev: Evaluator, fy: float, rings: int = 10) -> SpotResult:
    sysm = ev.system
    px, py = hexapolar(rings)
    ch = ev.chief(fy)
    x0, y0 = ch.P[0, 0], ch.P[0, 1]
    xs, ys, ws = [], [], []
    for wl, w in zip(sysm.wavelengths, sysm.wavelength_weights):
        r = ev.trace(fy, px, py, wl)
        xs.append(r.P[r.valid, 0] - x0)
        ys.append(r.P[r.valid, 1] - y0)
        ws.append(np.full(r.valid.sum(), w))
    X, Y, W = np.concatenate(xs), np.concatenate(ys), np.concatenate(ws)
    cx, cy = np.average(X, weights=W), np.average(Y, weights=W)
    d2 = (X - cx) ** 2 + (Y - cy) ** 2
    rms = math.sqrt(np.average(d2, weights=W))
    per = []
    for x, y in zip(xs, ys):
        per.append(math.sqrt(np.mean((x - x.mean()) ** 2 + (y - y.mean()) ** 2)) if x.size else math.nan)
    return SpotResult(fy, xs, ys, (x0, y0), rms, math.sqrt(d2.max()), per, (cx, cy))


# --------------------------------------------------------------------------
# 横収差・OPD ファン
# --------------------------------------------------------------------------
@dataclass
class FanResult:
    field: float
    pupil: np.ndarray
    tangential: list[np.ndarray]   # 波長ごと  (ey  または OPD)
    sagittal: list[np.ndarray]     # 波長ごと  (ex  または OPD)


def ray_fan(ev: Evaluator, fy: float, n: int = 61) -> FanResult:
    p = np.linspace(-1, 1, n)
    ch = ev.chief(fy)
    tan, sag = [], []
    for wl in ev.system.wavelengths:
        rt = ev.trace(fy, np.zeros(n), p, wl)
        rs = ev.trace(fy, p, np.zeros(n), wl)
        tan.append(rt.y - ch.P[0, 1])
        sag.append(rs.x - ch.P[0, 0])
    return FanResult(fy, p, tan, sag)


def opd_fan(ev: Evaluator, fy: float, n: int = 61) -> FanResult:
    p = np.linspace(-1, 1, n)
    tan, sag = [], []
    for wl in ev.system.wavelengths:
        tan.append(ev.opd(fy, np.zeros(n), p, wl)[0])
        sag.append(ev.opd(fy, p, np.zeros(n), wl)[0])
    return FanResult(fy, p, tan, sag)


# --------------------------------------------------------------------------
# 波面収差マップ
# --------------------------------------------------------------------------
@dataclass
class WavefrontResult:
    field: float
    wavelength: float
    px: np.ndarray
    py: np.ndarray
    opd: np.ndarray       # [waves]  瞳外は nan
    rms: float            # ピストン・チルト除去後 RMS [waves]
    pv: float             # ピストン・チルト除去後 P-V [waves]
    strehl: float         # Maréchal 近似 exp(-(2π σ)^2)


def wavefront(ev: Evaluator, fy: float, wl: float | None = None, n: int = 65,
              remove_tilt: bool = True) -> WavefrontResult:
    wl = ev.system.primary_wavelength if wl is None else wl
    px, py, mask = square_grid(n)
    w, valid = ev.opd(fy, px[mask], py[mask], wl)
    W = np.full(px.shape, np.nan)
    W[mask] = w
    ok = np.isfinite(W)
    x, y, z = px[ok], py[ok], W[ok]
    A = np.stack([np.ones_like(x), x, y], axis=1) if remove_tilt else np.ones((x.size, 1))
    coef, *_ = np.linalg.lstsq(A, z, rcond=None)
    res = z - A @ coef
    Wr = np.full(px.shape, np.nan)
    Wr[ok] = res
    rms = float(np.sqrt(np.mean(res**2)))
    return WavefrontResult(fy, wl, px, py, Wr, rms, float(res.max() - res.min()),
                           math.exp(-(2 * math.pi * rms) ** 2))


# --------------------------------------------------------------------------
# 像面湾曲・歪曲
# --------------------------------------------------------------------------
@dataclass
class FieldCurveResult:
    fields: np.ndarray
    tangential: list[np.ndarray]   # 波長ごと, 像面からの焦点ずれ [mm]
    sagittal: list[np.ndarray]
    distortion: np.ndarray         # [%] 主波長
    real_height: np.ndarray        # 主光線像高 [mm]
    paraxial_height: np.ndarray    # 近軸像高 [mm]


def field_curves(ev: Evaluator, n: int = 25, delta: float = 1e-3) -> FieldCurveResult:
    sysm = ev.system
    fmax = sysm.max_field
    fields = np.linspace(0, fmax, n)
    tan, sag = [], []
    for wl in sysm.wavelengths:
        zt, zs = [], []
        for f in fields:
            r = ev.trace(f, [0.0, 0.0, delta], [0.0, delta, 0.0], wl)
            m = r.D[:, :2] / r.D[:, 2:3]
            dy0, dmy = r.P[1, 1] - r.P[0, 1], m[1, 1] - m[0, 1]
            dx0, dmx = r.P[2, 0] - r.P[0, 0], m[2, 0] - m[0, 0]
            zt.append(-dy0 / dmy if dmy != 0 else np.nan)
            zs.append(-dx0 / dmx if dmx != 0 else np.nan)
        tan.append(np.array(zt))
        sag.append(np.array(zs))
    # 歪曲: 実主光線像高 vs 近軸像高
    wl = sysm.primary_wavelength
    real = np.array([ev.trace(f, 0.0, 0.0, wl).P[0, 1] for f in fields])
    par = []
    for f in fields:
        y1, u0 = chief_ray_start(sysm, f, ev.fo.ep_z)
        par.append(trace_paraxial(sysm, y1, u0, wl).y[-1])
    par = np.array(par)
    with np.errstate(invalid="ignore", divide="ignore"):
        dist = np.where(np.abs(par) > 0, 100 * (real - par) / par, 0.0)
    return FieldCurveResult(fields, tan, sag, dist, real, par)


# --------------------------------------------------------------------------
# PSF / MTF（FFT 法）
# --------------------------------------------------------------------------
@dataclass
class MTFResult:
    field: float
    freq: np.ndarray              # [cycles/mm]
    tangential: np.ndarray
    sagittal: np.ndarray
    diffraction_limit: np.ndarray
    cutoff: float                 # 主波長のカットオフ周波数


@dataclass
class PSFResult:
    field: float
    psf: np.ndarray               # 規格化（無収差ピーク = 1）
    pixel: float                  # [mm]
    strehl: float


def _pupil_function(ev: Evaluator, fy: float, wl: float, n: int):
    px, py, mask = square_grid(n)
    w, _ = ev.opd(fy, px[mask], py[mask], wl)
    amp = np.zeros(px.shape)
    ph = np.zeros(px.shape)
    ok = np.isfinite(w)
    idx = np.flatnonzero(mask.ravel())
    amp.ravel()[idx[ok]] = 1.0
    ph.ravel()[idx[ok]] = w[ok]
    return amp * np.exp(2j * np.pi * ph), mask.astype(float)


def _otf(pupil: np.ndarray, pad: int) -> np.ndarray:
    n = pupil.shape[0]
    m = n * pad
    P = np.zeros((m, m), complex)
    P[:n, :n] = pupil
    F = np.fft.fft2(P)
    otf = np.fft.ifft2(np.abs(F) ** 2)
    return otf / otf[0, 0].real if otf[0, 0].real != 0 else otf


def mtf(ev: Evaluator, fy: float, n: int = 64, pad: int = 4, nfreq: int = 101,
        max_freq: float | None = None) -> MTFResult:
    sysm = ev.system
    fno = ev.fo.working_fno
    cut_primary = 1.0 / (sysm.primary_wavelength * 1e-3 * fno)
    fmax = max_freq if max_freq else cut_primary
    freq = np.linspace(0, fmax, nfreq)
    tot = sum(sysm.wavelength_weights)
    T = np.zeros(nfreq, complex)
    S = np.zeros(nfreq, complex)
    DL = np.zeros(nfreq)
    for wl, wgt in zip(sysm.wavelengths, sysm.wavelength_weights):
        cutoff = 1.0 / (wl * 1e-3 * fno)
        dnu = cutoff / (n - 1)
        pupil, _ = _pupil_function(ev, fy, wl, n)
        otf = _otf(pupil, pad)
        k = np.arange(n)
        # y 方向（行方向）= タンジェンシャル, x 方向 = サジタル
        ot, os_ = otf[k, 0], otf[0, k]
        kf = freq / dnu
        T += wgt * (np.interp(kf, k, ot.real, right=0) + 1j * np.interp(kf, k, ot.imag, right=0))
        S += wgt * (np.interp(kf, k, os_.real, right=0) + 1j * np.interp(kf, k, os_.imag, right=0))
        v = np.clip(freq / cutoff, 0, 1)
        phi = np.arccos(v)
        DL += wgt * (2 / np.pi) * (phi - np.cos(phi) * np.sin(phi))
    return MTFResult(fy, freq, np.abs(T) / tot, np.abs(S) / tot, DL / tot, cut_primary)


def psf(ev: Evaluator, fy: float, wl: float | None = None, n: int = 64, pad: int = 8) -> PSFResult:
    sysm = ev.system
    wl = sysm.primary_wavelength if wl is None else wl
    pupil, mask = _pupil_function(ev, fy, wl, n)
    m = n * pad

    def intensity(p):
        P = np.zeros((m, m), complex)
        P[:n, :n] = p
        return np.fft.fftshift(np.abs(np.fft.ifft2(P)) ** 2)  # ifft: 像の向きを光線追跡と一致させる

    ideal = intensity(mask).max()
    I = intensity(pupil) / ideal
    cutoff = 1.0 / (wl * 1e-3 * ev.fo.working_fno)
    pixel = (n - 1) / (m * cutoff)
    return PSFResult(fy, I, pixel, float(I.max()))


def distortion(ev: Evaluator, fy: float) -> float:
    """視野 fy における歪曲 [%]（主波長の実主光線像高と近軸像高の比較）。"""
    sysm = ev.system
    if fy == 0:
        return 0.0
    real = ev.chief(fy).P[0, 1]
    y1, u0 = chief_ray_start(sysm, fy, ev.fo.ep_z)
    par = trace_paraxial(sysm, y1, u0, sysm.primary_wavelength).y[-1]
    return 100.0 * (real - par) / par


def lateral_color(ev: Evaluator) -> float:
    """最大画角における主光線像高の差 (最短波長 - 最長波長) [mm]。"""
    sysm = ev.system
    ys = min(sysm.wavelengths), max(sysm.wavelengths)
    f = sysm.max_field
    return float(ev.chief(f, ys[0]).P[0, 1] - ev.chief(f, ys[1]).P[0, 1])


def axial_color(ev: Evaluator) -> float:
    """近軸像点位置の差 (最短波長 - 最長波長) [mm]。"""
    sysm = ev.system
    a = first_order(sysm, min(sysm.wavelengths)).image_distance
    b = first_order(sysm, max(sysm.wavelengths)).image_distance
    return a - b


def trace_record(ev: Evaluator, fy: float, py, wl: float | None = None) -> TraceResult:
    """レイアウト描画用: 子午面内の光線を各面の交点つきで追跡する。"""
    wl = ev.system.primary_wavelength if wl is None else wl
    py = np.asarray(py, dtype=float)
    return ev.trace(fy, np.zeros_like(py), py, wl, record=True)
