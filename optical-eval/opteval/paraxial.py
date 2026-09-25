"""近軸光線追跡（y-nu トレース）、一次量、Seidel 収差係数。

符号規約: 光は +z 方向へ進む。u は光線の傾き dy/dz。
物体点は +y 側にあるものとする（画角 θ の主光線は u = -tanθ）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .system import OpticalSystem


@dataclass
class ParaxialRay:
    y: np.ndarray       # 面 1..IMG での光線高
    u_in: np.ndarray    # 各面への入射傾き
    u_out: np.ndarray   # 各面からの射出傾き


def trace_paraxial(system: OpticalSystem, y1: float, u0: float, wl: float) -> ParaxialRay:
    """面 1 で高さ y1、物体空間の傾き u0 の近軸光線を像面まで追跡する。"""
    n = system.index(0, wl)
    y, u = y1, u0
    ys, uin, uout = [], [], []
    last = system.image_index
    for j in range(1, last + 1):
        s = system.surfaces[j]
        ys.append(y)
        uin.append(u)
        if j == last:
            uout.append(u)
            break
        n2 = system.index(j, wl)
        u2 = (n * u - y * (n2 - n) * s.curvature) / n2
        uout.append(u2)
        y = y + s.thickness * u2
        n, u = n2, u2
    return ParaxialRay(np.array(ys), np.array(uin), np.array(uout))


@dataclass
class FirstOrder:
    efl: float                # 焦点距離
    bfl: float                # バックフォーカス（最終面→近軸焦点）
    ffl: float                # 面 1 から前側焦点までの符号付き距離（通常は負）
    image_distance: float     # 最終面 → 近軸像面
    ep_z: float               # 入射瞳位置（面 1 基準）
    ep_radius: float          # 入射瞳半径
    xp_z: float               # 射出瞳位置（像面基準）
    xp_radius: float          # 射出瞳半径
    fno: float                # F ナンバー (EFL / EPD)
    working_fno: float        # 作動 F ナンバー 1/(2 n' |u'|)
    na_image: float           # 像側 NA（近軸）
    magnification: float      # 近軸倍率（有限物体のみ）
    image_height: float       # 最大画角での近軸像高
    lagrange: float           # ラグランジュ不変量
    total_track: float        # 面 1 → 像面
    marginal: ParaxialRay
    chief: ParaxialRay        # 最大画角の主光線
    chief_u0: float           # 最大画角主光線の物体空間傾き
    chief_y1: float


def _entrance_pupil_z(system: OpticalSystem, wl: float) -> float:
    s = system.stop_index
    ya = trace_paraxial(system, 1.0, 0.0, wl).y[s - 1]
    yb = trace_paraxial(system, 0.0, 1.0, wl).y[s - 1]
    if abs(ya) < 1e-15:
        raise ValueError("入射瞳が無限遠です（物体側テレセントリック）: 未対応")
    return yb / ya


def chief_ray_start(system: OpticalSystem, fy: float, ep_z: float) -> tuple[float, float]:
    """画角/物体高 fy に対する近軸主光線の (y1, u0)。"""
    if system.infinite_object:
        u0 = -math.tan(math.radians(fy)) if system.field_type == "angle" else math.nan
        if math.isnan(u0):
            raise ValueError("無限遠物体では field type は 'angle' を指定してください")
        return -u0 * ep_z, u0
    d0 = system.surfaces[0].thickness
    if system.field_type == "angle":
        u0 = -math.tan(math.radians(fy))
    else:
        u0 = -fy / (d0 + ep_z)
    return -u0 * ep_z, u0


def first_order(system: OpticalSystem, wl: float | None = None) -> FirstOrder:
    wl = system.primary_wavelength if wl is None else wl
    last = system.image_index
    n_img = system.index(last - 1, wl)
    n_obj = system.index(0, wl)

    # 焦点距離: 平行光線 y=1
    pr = trace_paraxial(system, 1.0, 0.0, wl)
    u_k = pr.u_out[-2]
    efl = -1.0 / u_k if u_k != 0 else math.inf
    bfl = -pr.y[-2] / u_k if u_k != 0 else math.inf
    # 前側焦点: 光軸上 z=zf から出て像側で平行になる光線 (y1 = -zf*u) を求める
    pb = trace_paraxial(system, 0.0, 1.0, wl)
    ffl = pb.u_out[-2] / u_k if u_k != 0 else math.inf

    ep_z = _entrance_pupil_z(system, wl)

    # 入射瞳径
    if system.aperture_type == "EPD":
        epr = system.aperture_value / 2
    elif system.aperture_type == "FNO":
        if not system.infinite_object:
            raise ValueError("FNO 指定は無限遠物体のみ対応")
        epr = abs(efl) / system.aperture_value / 2
    else:  # NAO
        if system.infinite_object:
            raise ValueError("NAO 指定は有限物体のみ対応")
        u = math.tan(math.asin(system.aperture_value / n_obj))
        epr = u * (system.surfaces[0].thickness + ep_z)

    # 周辺光線
    if system.infinite_object:
        mar = trace_paraxial(system, epr, 0.0, wl)
    else:
        d0 = system.surfaces[0].thickness
        u0 = epr / (d0 + ep_z)
        mar = trace_paraxial(system, u0 * d0, u0, wl)
    u_mk = mar.u_out[-2]
    image_distance = -mar.y[-2] / u_mk if u_mk != 0 else math.inf

    # 主光線（最大画角）
    y1c, u0c = chief_ray_start(system, system.max_field, ep_z)
    chi = trace_paraxial(system, y1c, u0c, wl)

    # 射出瞳: 主光線が像空間で光軸と交わる位置（像面基準）
    t_last = system.surfaces[last - 1].thickness
    u_ck = chi.u_out[-2]
    if u_ck != 0:
        xp_from_last = -chi.y[-2] / u_ck
        xp_z = xp_from_last - t_last
        xp_radius = abs(mar.y[-2] + u_mk * xp_from_last)
    else:
        xp_z, xp_radius = -math.inf, math.nan

    lagrange = n_obj * (u0c * mar.y[0] - mar.u_in[0] * y1c)
    na_img = n_img * abs(math.sin(math.atan(u_mk)))
    wfno = 1.0 / (2.0 * na_img) if na_img > 0 else math.inf
    if system.infinite_object:
        mag = 0.0
    else:
        mag = (n_obj * mar.u_in[0]) / (n_img * u_mk) if u_mk != 0 else math.inf
    total_track = sum(s.thickness for s in system.surfaces[1:last])
    return FirstOrder(
        efl=efl, bfl=bfl, ffl=ffl, image_distance=image_distance, ep_z=ep_z, ep_radius=epr,
        xp_z=xp_z, xp_radius=xp_radius, fno=abs(efl) / (2 * epr), working_fno=wfno,
        na_image=na_img, magnification=mag, image_height=chi.y[-1], lagrange=lagrange,
        total_track=total_track, marginal=mar, chief=chi, chief_u0=u0c, chief_y1=y1c,
    )


def focus_paraxial(system: OpticalSystem) -> float:
    """最終面→像面距離を近軸像点に合わせる（CODE V の PIM ソルブ相当）。"""
    fo = first_order(system)
    system.surfaces[system.image_index - 1].thickness = fo.image_distance
    return fo.image_distance


# --------------------------------------------------------------------------
# Seidel 収差
# --------------------------------------------------------------------------
@dataclass
class Seidel:
    SI: np.ndarray     # 球面収差
    SII: np.ndarray    # コマ
    SIII: np.ndarray   # 非点収差
    SIV: np.ndarray    # ペッツバール
    SV: np.ndarray     # 歪曲
    CI: np.ndarray     # 軸上色収差
    CII: np.ndarray    # 倍率色収差
    wavelength: float  # 主波長 [µm]

    def totals(self) -> dict[str, float]:
        return {k: float(getattr(self, k).sum()) for k in ("SI", "SII", "SIII", "SIV", "SV", "CI", "CII")}

    def wave_coefficients(self) -> dict[str, float]:
        """波面収差係数 [waves]（瞳端・最大画角）。"""
        t = self.totals()
        lam = self.wavelength * 1e-3
        return {
            "W040 (球面)": t["SI"] / 8 / lam,
            "W131 (コマ)": t["SII"] / 2 / lam,
            "W222 (非点)": t["SIII"] / 2 / lam,
            "W220 (像面湾曲)": (t["SIII"] + t["SIV"]) / 4 / lam,
            "W311 (歪曲)": t["SV"] / 2 / lam,
        }


def seidel(system: OpticalSystem) -> Seidel:
    """Welford の表記による Seidel 和（面ごと）。"""
    wl = system.primary_wavelength
    wl_short, wl_long = min(system.wavelengths), max(system.wavelengths)
    fo = first_order(system, wl)
    mar, chi = fo.marginal, fo.chief
    n0 = system.index(0, wl)
    H = n0 * (chi.u_in[0] * mar.y[0] - mar.u_in[0] * chi.y[0])
    nsurf = system.image_index - 1
    out = {k: np.zeros(nsurf) for k in ("SI", "SII", "SIII", "SIV", "SV", "CI", "CII")}
    for j in range(1, nsurf + 1):
        s = system.surfaces[j]
        c = s.curvature
        n, n2 = system.index(j - 1, wl), system.index(j, wl)
        y, yb = mar.y[j - 1], chi.y[j - 1]
        u, u2 = mar.u_in[j - 1], mar.u_out[j - 1]
        ub = chi.u_in[j - 1]
        A = n * (y * c + u)
        Ab = n * (yb * c + ub)
        d_un = u2 / n2 - u / n
        d_1n = 1 / n2 - 1 / n
        d_1n2 = 1 / n2**2 - 1 / n**2
        si = -A * A * y * d_un
        sii = -A * Ab * y * d_un
        siii = -Ab * Ab * y * d_un
        siv = -H * H * c * d_1n
        sv = -Ab**3 * y * d_1n2 + Ab * yb * c * (2 * Ab * y - A * yb) * d_1n
        # 非球面（コーニック・高次係数）の 4 次項の寄与
        a4 = s.conic * c**3 / 8 + (s.aspheric[0] if s.aspheric else 0.0)
        if a4 and y != 0:
            ds = 8 * a4 * (n2 - n) * y**4
            q = yb / y
            si += ds
            sii += q * ds
            siii += q * q * ds
            sv += q**3 * ds
        dn = system.index(j - 1, wl_short) - system.index(j - 1, wl_long)
        dn2 = system.index(j, wl_short) - system.index(j, wl_long)
        d_dnn = dn2 / n2 - dn / n
        out["SI"][j - 1] = si
        out["SII"][j - 1] = sii
        out["SIII"][j - 1] = siii
        out["SIV"][j - 1] = siv
        out["SV"][j - 1] = sv
        out["CI"][j - 1] = A * y * d_dnn
        out["CII"][j - 1] = Ab * y * d_dnn
    return Seidel(wavelength=wl, **out)
