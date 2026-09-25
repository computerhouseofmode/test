"""Web UI 用の API（HTTP から独立した純粋関数）。"""

from __future__ import annotations

import base64
import io
import math
import threading
from pathlib import Path

import numpy as np

from .. import analysis as an
from .. import plots, report
from ..glass import FRAUNHOFER, abbe_number, catalog, refractive_index
from ..optimize import optimize as run_optimize
from ..paraxial import seidel
from ..raytrace import auto_semi_diameters
from ..system import OpticalSystem

# matplotlib (pyplot) はスレッドセーフではないため計算全体を直列化する
LOCK = threading.Lock()
EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


class ApiError(Exception):
    status = 400


CALC_ERRORS = (ValueError, KeyError, IndexError, TypeError, ZeroDivisionError, OverflowError,
               FloatingPointError, np.linalg.LinAlgError)


def _msg(e: Exception) -> str:
    # KeyError の str() は引用符付きになるため引数をそのまま使う
    return str(e.args[0]) if isinstance(e, KeyError) and e.args else str(e)


def _system(d) -> OpticalSystem:
    if not isinstance(d, dict):
        raise ApiError("lens が指定されていません")
    try:
        return OpticalSystem.from_dict(d)
    except CALC_ERRORS as e:
        raise ApiError(f"レンズデータが不正です: {_msg(e)}") from None


def _num(v):
    """JSON に載せられる値へ（inf / nan は文字列・None に）。"""
    if isinstance(v, (float, np.floating)):
        v = float(v)
        if math.isnan(v):
            return None
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
    return v


def _png(fig) -> str:
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


FIGURES = {
    "layout": lambda ev, o: plots.plot_layout(ev, rays_per_field=int(o.get("rays", 7))),
    "spot": lambda ev, o: plots.plot_spots(ev, rings=int(o.get("rings", 10))),
    "ray_fan": lambda ev, o: plots.plot_ray_fans(ev),
    "opd_fan": lambda ev, o: plots.plot_opd_fans(ev),
    "field_curves": lambda ev, o: plots.plot_field_curves(ev),
    "wavefront": lambda ev, o: plots.plot_wavefronts(ev),
    "mtf": lambda ev, o: plots.plot_mtf(ev, max_freq=float(o["max_freq"]) if o.get("max_freq") else None),
    "psf": lambda ev, o: plots.plot_psfs(ev),
    "seidel": lambda ev, o: plots.plot_seidel(ev),
}


def summary(ev: an.Evaluator) -> dict:
    sysm = ev.system
    wl = sysm.primary_wavelength
    sd = auto_semi_diameters(sysm)
    surf = [{"n": _num(refractive_index(s.material, wl)), "sd": _num(sd[i])} for i, s in enumerate(sysm.surfaces)]
    sh, sr = report.seidel_rows(ev)
    return {
        "title": sysm.title,
        "surfaces": surf,
        "first_order": [list(r) for r in report.first_order_rows(ev)],
        "performance": {"header": report.performance_header(ev), "rows": report.performance_rows(ev)},
        "seidel": {"header": sh, "rows": sr,
                   "wave": {k: _num(v) for k, v in seidel(sysm).wave_coefficients().items()}},
        "efl": _num(ev.fo.efl),
        "fno": _num(ev.fo.fno),
    }


def analyze(payload: dict) -> dict:
    sysm = _system(payload.get("lens"))
    kind = payload.get("analysis", "summary")
    opts = payload.get("options") or {}
    if kind != "summary" and kind not in FIGURES:
        raise ApiError(f"未知の解析: {kind}")
    with LOCK:
        try:
            ev = an.Evaluator(sysm)
            if kind == "summary":
                return summary(ev)
            return {"image": _png(FIGURES[kind](ev, opts))}
        except CALC_ERRORS as e:
            raise ApiError(f"計算できません: {_msg(e)}") from None
        finally:
            import matplotlib.pyplot as plt

            plt.close("all")


def optimize(payload: dict) -> dict:
    sysm = _system(payload.get("lens"))
    cfg = payload.get("config") or sysm.optimization or {}
    if not cfg.get("variables"):
        raise ApiError("変数が指定されていません（レンズデータの V ボタンか最適化タブで追加）")
    n = len(sysm.surfaces)
    for v in cfg["variables"]:
        if not (0 < int(v.get("surface", -1)) < n - 1):
            raise ApiError(f"変数の面番号が範囲外です: {v.get('surface')}")
    cfg = dict(cfg)
    cfg["iterations"] = max(1, min(int(cfg.get("iterations", 50)), 500))
    with LOCK:
        try:
            res = run_optimize(sysm, cfg)
        except CALC_ERRORS as e:
            raise ApiError(f"最適化できません: {_msg(e)}") from None
    out = res.system.to_dict()
    out["optimization"] = payload.get("config") or sysm.optimization
    return {
        "lens": out,
        "merit_history": [_num(m) for m in res.merit_history],
        "rms_spot_um": [_num(v) for v in res.rms_spot_um],
    }


def html_report(payload: dict) -> str:
    sysm = _system(payload.get("lens"))
    with LOCK:
        try:
            return report.html_report(an.Evaluator(sysm))
        except CALC_ERRORS as e:
            raise ApiError(f"レポートを作成できません: {_msg(e)}") from None


def glasses() -> list[dict]:
    wd = FRAUNHOFER["d"]
    return [{"name": g, "nd": round(refractive_index(g, wd), 5), "vd": round(abbe_number(g), 2)} for g in catalog()]


def examples() -> list[dict]:
    out = []
    for p in sorted(EXAMPLES_DIR.glob("*.json")):
        try:
            title = OpticalSystem.load(p).title
        except Exception:  # noqa: BLE001  壊れたファイルは一覧から除外
            continue
        out.append({"id": p.stem, "title": title or p.stem})
    return out


def example(name: str) -> dict:
    ids = {e["id"] for e in examples()}
    if name not in ids:
        raise ApiError(f"サンプルがありません: {name}")
    return OpticalSystem.load(EXAMPLES_DIR / f"{name}.json").to_dict()
