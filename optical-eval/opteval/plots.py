"""matplotlib による評価図の描画。"""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from . import analysis as an  # noqa: E402
from .glass import is_air  # noqa: E402
from .raytrace import auto_semi_diameters, sag  # noqa: E402

FIELD_COLORS = ["#1f77b4", "#2ca02c", "#d62728", "#ff7f0e", "#9467bd", "#8c564b", "#e377c2"]


def wl_color(wl_um: float) -> str:
    """波長 [µm] を表示色に変換（おおよその可視スペクトル）。"""
    w = wl_um * 1000
    if w < 440:
        r, g, b = 0.45, 0.0, 0.9
    elif w < 490:
        r, g, b = 0.0, (w - 440) / 50, 1.0
    elif w < 510:
        r, g, b = 0.0, 0.8, (510 - w) / 20
    elif w < 580:
        r, g, b = (w - 510) / 70, 0.75, 0.0
    elif w < 645:
        r, g, b = 1.0, 0.75 * (645 - w) / 65, 0.0
    else:
        r, g, b = 0.85, 0.0, 0.0
    return matplotlib.colors.to_hex((r, g, b))


def _field_label(sysm, f):
    return f"{f:g}°" if sysm.field_type == "angle" else f"{f:g} mm"


def plot_layout(ev: an.Evaluator, ax=None, rays_per_field: int = 7):
    sysm = ev.system
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4.5))
    zv = sysm.vertex_positions()
    sd = auto_semi_diameters(sysm)
    last = sysm.image_index

    def profile(j):
        h = sd[j]
        y = np.linspace(-h, h, 81)
        return zv[j] + sag(sysm.surfaces[j], np.zeros_like(y), y), y

    # レンズ要素
    for j in range(1, last):
        s = sysm.surfaces[j]
        z1, y1 = profile(j)
        ax.plot(z1, y1, color="k", lw=1.2)
        if not is_air(s.material) and j + 1 < last:
            z2, y2 = profile(j + 1)
            h = max(sd[j], sd[j + 1])
            for sgn in (1, -1):
                ze1, ze2 = z1[0 if sgn < 0 else -1], z2[0 if sgn < 0 else -1]
                ax.plot([ze1, ze1, ze2, ze2], [sgn * sd[j], sgn * h, sgn * h, sgn * sd[j + 1]],
                        color="k", lw=1.2)
            zz = np.concatenate([z1, z2[::-1]])
            yy = np.concatenate([y1, y2[::-1]])
            ax.fill(zz, yy, color="#a6cee3", alpha=0.35, lw=0)
        if s.stop:
            h = sd[j]
            ax.plot([zv[j]] * 2, [h, h * 1.25], color="k", lw=2)
            ax.plot([zv[j]] * 2, [-h, -h * 1.25], color="k", lw=2)
    # 像面
    zi, yi = profile(last)
    ax.plot(zi, yi, color="k", lw=1.5)

    # 光線
    track = zv[last] - zv[1] if last > 1 else 1.0
    lead = 0.15 * max(track, 1.0)
    py = np.linspace(-1, 1, rays_per_field)
    for fi, f in enumerate(sysm.fields):
        col = FIELD_COLORS[fi % len(FIELD_COLORS)]
        P0, D0 = ev.gen.rays(f, np.zeros_like(py), py)
        r = an.trace_record(ev, f, py)
        for k in range(len(py)):
            zs, ys = [], []
            # 物体側の区間
            Q1 = r.history[0][k]
            if sysm.infinite_object:
                t = (Q1[2] - (-lead)) / D0[k, 2]
                start = Q1 - D0[k] * t
            else:
                start = P0[k]
            zs.append(start[2])
            ys.append(start[1])
            for j, Q in enumerate(r.history, start=1):
                if not np.all(np.isfinite(Q[k])):
                    break
                zs.append(zv[j] + Q[k, 2])
                ys.append(Q[k, 1])
            ax.plot(zs, ys, color=col, lw=0.7, alpha=0.9)
        ax.plot([], [], color=col, label=_field_label(sysm, f))
    ax.set_aspect("equal")
    ax.set_xlabel("z [mm]")
    ax.set_ylabel("y [mm]")
    ax.legend(loc="upper left", fontsize=8, title="Field")
    ax.set_title("Layout")
    ax.grid(alpha=0.2)
    return ax.figure


def plot_spots(ev: an.Evaluator, rings: int = 10):
    sysm = ev.system
    nf = len(sysm.fields)
    spots = [an.spot(ev, f, rings) for f in sysm.fields]
    lim = max(max(s.geo for s in spots) * 1e3, 1e-3) * 1.15
    fig, axes = plt.subplots(1, nf, figsize=(3.2 * nf, 3.6), squeeze=False)
    airy = 1.22 * sysm.primary_wavelength * ev.fo.working_fno  # µm
    for ax, sp in zip(axes[0], spots):
        cx, cy = sp.centroid
        for x, y, wl in zip(sp.x, sp.y, sysm.wavelengths):
            ax.plot((x - cx) * 1e3, (y - cy) * 1e3, ".", ms=2.5, color=wl_color(wl), label=f"{wl:.4f}")
        th = np.linspace(0, 2 * np.pi, 200)
        ax.plot(airy * np.cos(th), airy * np.sin(th), "k--", lw=0.6)
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_aspect("equal")
        ax.set_title(f"{_field_label(sysm, sp.field)}\nRMS {sp.rms*1e3:.2f} µm  GEO {sp.geo*1e3:.2f} µm",
                     fontsize=9)
        ax.set_xlabel("x [µm]")
        ax.grid(alpha=0.2)
    axes[0][0].set_ylabel("y [µm]")
    axes[0][0].legend(fontsize=7, markerscale=3, title="λ [µm]", title_fontsize=7)
    fig.suptitle(f"Spot diagram (centroid, dashed = Airy radius {airy:.2f} µm)", fontsize=10)
    fig.tight_layout()
    return fig


def _plot_fans(ev: an.Evaluator, fans, ylabel: str, title: str, scale: float):
    sysm = ev.system
    nf = len(fans)
    fig, axes = plt.subplots(nf, 2, figsize=(8, 2.4 * nf), squeeze=False, sharey=True)
    for i, fan in enumerate(fans):
        for k, wl in enumerate(sysm.wavelengths):
            axes[i][0].plot(fan.pupil, fan.tangential[k] * scale, color=wl_color(wl), lw=1.2, label=f"{wl:.4f}")
            axes[i][1].plot(fan.pupil, fan.sagittal[k] * scale, color=wl_color(wl), lw=1.2)
        axes[i][0].set_ylabel(f"{_field_label(sysm, fan.field)}\n{ylabel}", fontsize=8)
        for ax in axes[i]:
            ax.axhline(0, color="k", lw=0.5)
            ax.axvline(0, color="k", lw=0.5)
            ax.grid(alpha=0.2)
    axes[0][0].set_title("Tangential (Py)")
    axes[0][1].set_title("Sagittal (Px)")
    axes[-1][0].set_xlabel("Normalized pupil")
    axes[-1][1].set_xlabel("Normalized pupil")
    axes[0][0].legend(fontsize=7, title="λ [µm]", title_fontsize=7)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    return fig


def plot_ray_fans(ev: an.Evaluator):
    fans = [an.ray_fan(ev, f) for f in ev.system.fields]
    return _plot_fans(ev, fans, "ε [µm]", "Transverse ray aberration", 1e3)


def plot_opd_fans(ev: an.Evaluator):
    fans = [an.opd_fan(ev, f) for f in ev.system.fields]
    return _plot_fans(ev, fans, "OPD [waves]", "Optical path difference", 1.0)


def plot_field_curves(ev: an.Evaluator):
    sysm = ev.system
    fc = an.field_curves(ev)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8, 4), sharey=True)
    for k, wl in enumerate(sysm.wavelengths):
        c = wl_color(wl)
        a1.plot(fc.tangential[k], fc.fields, color=c, lw=1.3, label=f"T {wl:.4f}")
        a1.plot(fc.sagittal[k], fc.fields, color=c, lw=1.3, ls="--", label=f"S {wl:.4f}")
    a1.axvline(0, color="k", lw=0.5)
    a1.set_xlabel("Focus shift [mm]")
    a1.set_ylabel("Field " + ("[deg]" if sysm.field_type == "angle" else "[mm]"))
    a1.set_title("Astigmatic field curves")
    a1.legend(fontsize=7)
    a1.grid(alpha=0.2)
    a2.plot(fc.distortion, fc.fields, color="k", lw=1.3)
    a2.axvline(0, color="k", lw=0.5)
    a2.set_xlabel("Distortion [%]")
    a2.set_title("Distortion")
    a2.grid(alpha=0.2)
    fig.tight_layout()
    return fig


def plot_mtf(ev: an.Evaluator, max_freq: float | None = None):
    sysm = ev.system
    fig, ax = plt.subplots(figsize=(7, 4.5))
    dl = None
    for i, f in enumerate(sysm.fields):
        m = an.mtf(ev, f, max_freq=max_freq)
        col = FIELD_COLORS[i % len(FIELD_COLORS)]
        ax.plot(m.freq, m.tangential, color=col, lw=1.3, label=f"{_field_label(sysm, f)} T")
        ax.plot(m.freq, m.sagittal, color=col, lw=1.3, ls="--", label=f"{_field_label(sysm, f)} S")
        dl = m
    ax.plot(dl.freq, dl.diffraction_limit, color="k", lw=1, label="Diffraction limit")
    ax.set_xlim(0, dl.freq[-1])
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("Spatial frequency [cycles/mm]")
    ax.set_ylabel("Modulus of OTF")
    ax.set_title("Polychromatic diffraction MTF")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    return fig


def plot_wavefronts(ev: an.Evaluator):
    sysm = ev.system
    nf = len(sysm.fields)
    fig, axes = plt.subplots(1, nf, figsize=(3.4 * nf, 3.4), squeeze=False)
    for ax, f in zip(axes[0], sysm.fields):
        wf = an.wavefront(ev, f)
        v = np.nanmax(np.abs(wf.opd)) or 1e-6
        im = ax.imshow(wf.opd, origin="lower", extent=(-1, 1, -1, 1), cmap="RdBu_r", vmin=-v, vmax=v)
        ax.set_title(f"{_field_label(sysm, f)}\nRMS {wf.rms:.3f} λ  PV {wf.pv:.3f} λ", fontsize=9)
        ax.set_xlabel("Px")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    axes[0][0].set_ylabel("Py")
    fig.suptitle(f"Wavefront map (tilt removed, λ = {sysm.primary_wavelength:.4f} µm)", fontsize=10)
    fig.tight_layout()
    return fig


def plot_psfs(ev: an.Evaluator, half_width_um: float | None = None):
    sysm = ev.system
    nf = len(sysm.fields)
    fig, axes = plt.subplots(1, nf, figsize=(3.4 * nf, 3.4), squeeze=False)
    hw = half_width_um or 6 * sysm.primary_wavelength * ev.fo.working_fno
    for ax, f in zip(axes[0], sysm.fields):
        p = an.psf(ev, f)
        m = p.psf.shape[0]
        c = m // 2
        k = max(2, int(math.ceil(hw * 1e-3 / p.pixel)))
        sub = p.psf[c - k:c + k + 1, c - k:c + k + 1]
        e = k * p.pixel * 1e3
        ax.imshow(sub, origin="lower", extent=(-e, e, -e, e), cmap="inferno")
        ax.set_title(f"{_field_label(sysm, f)}\nStrehl {p.strehl:.3f}", fontsize=9)
        ax.set_xlabel("x [µm]")
    axes[0][0].set_ylabel("y [µm]")
    fig.suptitle(f"FFT PSF (λ = {sysm.primary_wavelength:.4f} µm)", fontsize=10)
    fig.tight_layout()
    return fig


def plot_seidel(ev: an.Evaluator):
    from .paraxial import seidel

    sd = seidel(ev.system)
    keys = ["SI", "SII", "SIII", "SIV", "SV", "CI", "CII"]
    nsurf = len(sd.SI)
    labels = [str(j + 1) for j in range(nsurf)] + ["SUM"]
    fig, ax = plt.subplots(figsize=(9, 4))
    w = 0.8 / len(keys)
    x = np.arange(nsurf + 1)
    cmap = plt.get_cmap("tab10")
    for i, k in enumerate(keys):
        v = getattr(sd, k)
        ax.bar(x + (i - len(keys) / 2 + 0.5) * w, np.append(v, v.sum()), w, label=k, color=cmap(i))
    ax.axhline(0, color="k", lw=0.6)
    ax.axvline(nsurf - 0.5, color="k", lw=0.6, ls=":")
    ax.set_xticks(x, labels)
    ax.set_xlabel("Surface")
    ax.set_ylabel("Seidel sum [mm]")
    ax.set_title("Seidel aberration contributions")
    ax.legend(fontsize=8, ncol=7, loc="upper center", bbox_to_anchor=(0.5, -0.15))
    ax.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    return fig
