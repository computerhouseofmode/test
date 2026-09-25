"""テキスト / HTML レポートの生成。"""

from __future__ import annotations

import base64
import html
import io
import math
from pathlib import Path

import numpy as np

from . import analysis as an
from . import plots
from .glass import refractive_index
from .paraxial import seidel
from .raytrace import auto_semi_diameters


def _fmt(v: float, nd: int = 4) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    if isinstance(v, float) and math.isinf(v):
        return "Infinity"
    return f"{v:.{nd}f}"


def prescription_rows(ev: an.Evaluator) -> list[list[str]]:
    sysm = ev.system
    sd = auto_semi_diameters(sysm)
    wl = sysm.primary_wavelength
    rows = []
    last = sysm.image_index
    for i, s in enumerate(sysm.surfaces):
        name = "OBJ" if i == 0 else "IMG" if i == last else ("STO" if s.stop else str(i))
        n = refractive_index(s.material, wl)
        rows.append([
            name, _fmt(s.radius), _fmt(s.thickness), s.material, _fmt(n, 5) if i != last else "",
            _fmt(sd[i], 3) + ("" if s.semi_diameter is None else " (fixed)") if i else "",
            _fmt(s.conic, 4) if s.conic else "", " ".join(f"{a:.3e}" for a in s.aspheric), s.comment,
        ])
    return rows


PRESCRIPTION_HEADER = ["Surf", "Radius", "Thickness", "Material", "n", "Semi-Dia", "Conic", "Aspheric", "Comment"]


def first_order_rows(ev: an.Evaluator) -> list[tuple[str, str]]:
    fo, sysm = ev.fo, ev.system
    rows = [
        ("焦点距離 EFL", f"{fo.efl:.4f} mm"),
        ("バックフォーカス BFL", f"{fo.bfl:.4f} mm"),
        ("近軸像距離", f"{fo.image_distance:.4f} mm"),
        ("F ナンバー", f"{fo.fno:.3f}"),
        ("作動 F ナンバー", f"{fo.working_fno:.3f}"),
        ("像側 NA", f"{fo.na_image:.4f}"),
        ("入射瞳径 / 位置(S1基準)", f"{2*fo.ep_radius:.4f} mm / {fo.ep_z:.4f} mm"),
        ("射出瞳径 / 位置(像面基準)", f"{2*fo.xp_radius:.4f} mm / {fo.xp_z:.4f} mm"),
        ("最大像高（近軸）", f"{fo.image_height:.4f} mm"),
        ("全長（S1→像面）", f"{fo.total_track:.4f} mm"),
        ("Lagrange 不変量", f"{fo.lagrange:.5f}"),
        ("軸上色収差 (λmin-λmax)", f"{an.axial_color(ev)*1e3:.2f} µm"),
        ("倍率色収差 (最大画角)", f"{an.lateral_color(ev)*1e3:.2f} µm"),
    ]
    if not sysm.infinite_object:
        rows.insert(3, ("近軸倍率", f"{fo.magnification:.5f}"))
    return rows


def performance_rows(ev: an.Evaluator) -> list[list[str]]:
    sysm = ev.system
    rows = []
    for f in sysm.fields:
        sp = an.spot(ev, f)
        wf = an.wavefront(ev, f)
        m = an.mtf(ev, f, nfreq=201)
        half = m.cutoff / 4
        mt = float(np.interp(half, m.freq, m.tangential))
        ms = float(np.interp(half, m.freq, m.sagittal))
        dist = an.distortion(ev, f)
        rows.append([
            f"{f:g}", f"{ev.chief(f).P[0, 1]:.4f}", f"{sp.rms*1e3:.3f}", f"{sp.geo*1e3:.3f}",
            f"{wf.rms:.4f}", f"{wf.strehl:.3f}", f"{mt:.3f} / {ms:.3f}", f"{dist:.3f}",
        ])
    return rows


def performance_header(ev: an.Evaluator) -> list[str]:
    cut = ev.fo.working_fno and 1.0 / (ev.system.primary_wavelength * 1e-3 * ev.fo.working_fno)
    return ["Field", "Chief y [mm]", "RMS spot [µm]", "GEO spot [µm]", "RMS WFE [λ]", "Strehl*",
            f"MTF T/S @{cut/4:.0f} lp/mm", "Distortion [%]"]


def seidel_rows(ev: an.Evaluator) -> tuple[list[str], list[list[str]]]:
    sd = seidel(ev.system)
    keys = ["SI", "SII", "SIII", "SIV", "SV", "CI", "CII"]
    rows = []
    for j in range(len(sd.SI)):
        rows.append([str(j + 1)] + [f"{getattr(sd, k)[j]:.6f}" for k in keys])
    tot = sd.totals()
    rows.append(["SUM"] + [f"{tot[k]:.6f}" for k in keys])
    return ["Surf"] + keys, rows


def text_report(ev: an.Evaluator) -> str:
    sysm = ev.system
    out = []
    out.append(f"=== {sysm.title or 'Optical system'} ===")
    out.append("")
    out.append("[Prescription]")
    out.append(_table(PRESCRIPTION_HEADER, prescription_rows(ev)))
    out.append("")
    out.append("[Wavelengths] " + ", ".join(
        f"{w:.4f}µm(w={wt:g}){'*' if i == sysm.primary else ''}"
        for i, (w, wt) in enumerate(zip(sysm.wavelengths, sysm.wavelength_weights))))
    out.append(f"[Fields] {sysm.field_type}: " + ", ".join(f"{f:g}" for f in sysm.fields))
    out.append(f"[Aperture] {sysm.aperture_type} = {sysm.aperture_value:g}")
    out.append("")
    out.append("[First order]")
    for k, v in first_order_rows(ev):
        out.append(f"  {k:<28s} {v}")
    out.append("")
    out.append("[Seidel sums (mm)]")
    h, r = seidel_rows(ev)
    out.append(_table(h, r))
    out.append("  " + ", ".join(f"{k} = {v:.3f} λ" for k, v in seidel(sysm).wave_coefficients().items()))
    out.append("")
    out.append("[Image quality]")
    out.append(_table(performance_header(ev), performance_rows(ev)))
    out.append("  * Strehl は Maréchal 近似")
    return "\n".join(out)


def _table(header, rows) -> str:
    cols = list(zip(header, *rows))
    widths = [max(len(str(c)) for c in col) for col in cols]
    line = lambda r: "  ".join(str(c).rjust(w) for c, w in zip(r, widths))  # noqa: E731
    return "\n".join([line(header), "  ".join("-" * w for w in widths)] + [line(r) for r in rows])


def _fig_to_b64(fig) -> str:
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


FIGURES = [
    ("layout", "レイアウト", plots.plot_layout),
    ("spot", "スポットダイアグラム", plots.plot_spots),
    ("ray_fan", "横収差図 (Ray fan)", plots.plot_ray_fans),
    ("opd_fan", "波面収差図 (OPD fan)", plots.plot_opd_fans),
    ("field_curves", "像面湾曲・歪曲", plots.plot_field_curves),
    ("wavefront", "波面マップ", plots.plot_wavefronts),
    ("mtf", "MTF", plots.plot_mtf),
    ("psf", "PSF", plots.plot_psfs),
]


def save_figures(ev: an.Evaluator, outdir: str | Path) -> list[Path]:
    import matplotlib.pyplot as plt

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for key, _, fn in FIGURES:
        fig = fn(ev)
        p = outdir / f"{key}.png"
        fig.savefig(p, dpi=120)
        plt.close(fig)
        paths.append(p)
    return paths


def _html_table(header, rows) -> str:
    th = "".join(f"<th>{html.escape(str(h))}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def html_report(ev: an.Evaluator) -> str:
    sysm = ev.system
    title = html.escape(sysm.title or "Optical system")
    fo_rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>"
                      for k, v in first_order_rows(ev))
    sh, sr = seidel_rows(ev)
    wave = ", ".join(f"{html.escape(k)} = {v:.3f} λ" for k, v in seidel(sysm).wave_coefficients().items())
    figs = "".join(
        f'<section><h2>{html.escape(label)}</h2><img alt="{key}" src="data:image/png;base64,{_fig_to_b64(fn(ev))}"></section>'
        for key, label, fn in FIGURES)
    wls = ", ".join(f"{w:.4f} µm (w={wt:g}){' ★' if i == sysm.primary else ''}"
                    for i, (w, wt) in enumerate(zip(sysm.wavelengths, sysm.wavelength_weights)))
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#fff; --fg:#1b1f24; --muted:#59636e; --line:#d8dee4; --head:#f3f5f7; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#15181c; --fg:#e6e8eb; --muted:#9aa4ae; --line:#30363d; --head:#1f242a; }}
  img {{ background:#fff; }} }}
body {{ background:var(--bg); color:var(--fg); font-family: system-ui, -apple-system, "Hiragino Sans", "Noto Sans JP", sans-serif;
  max-width: 1100px; margin: 0 auto; padding: 24px 16px; line-height:1.5; }}
h1 {{ font-size: 1.5rem; margin: 0 0 4px; }} h2 {{ font-size:1.1rem; margin: 28px 0 8px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
.meta {{ color:var(--muted); font-size:.9rem; }}
.scroll {{ overflow-x:auto; }}
table {{ border-collapse: collapse; font-size: .85rem; font-variant-numeric: tabular-nums; }}
th, td {{ border:1px solid var(--line); padding: 3px 8px; text-align: right; white-space: nowrap; }}
thead th, tbody th {{ background: var(--head); text-align:left; }}
img {{ max-width: 100%; height:auto; border:1px solid var(--line); border-radius:4px; }}
</style></head><body>
<h1>{title}</h1>
<div class="meta">波長: {wls}<br>視野 ({sysm.field_type}): {", ".join(f"{f:g}" for f in sysm.fields)}　
開口: {sysm.aperture_type} = {sysm.aperture_value:g}</div>
<h2>レンズデータ</h2><div class="scroll">{_html_table(PRESCRIPTION_HEADER, prescription_rows(ev))}</div>
<h2>一次量（近軸）</h2><div class="scroll"><table>{fo_rows}</table></div>
<h2>結像性能</h2><div class="scroll">{_html_table(performance_header(ev), performance_rows(ev))}</div>
<p class="meta">Strehl は Maréchal 近似。スポットは重心基準、波面は主光線基準の参照球で評価。</p>
<h2>Seidel 収差係数 [mm]</h2><div class="scroll">{_html_table(sh, sr)}</div>
<p class="meta">{wave}</p>
{figs}
</body></html>
"""
