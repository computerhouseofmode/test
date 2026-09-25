"""減衰最小二乗法（Levenberg–Marquardt）による簡易最適化。

変数:   {"surface": 1, "param": "curvature" | "radius" | "thickness" | "conic" | "A4" | "A6" ...,
         "min": ..., "max": ...}
目標:   {"efl": 100.0, "efl_weight": 1.0}
その他: {"focus": "paraxial"}  … 評価前に像面を近軸像点へ移動
評価関数は全視野・全波長の横収差（主波長の重心ではなく主光線基準）の二乗和。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .analysis import Evaluator, hexapolar
from .paraxial import first_order, focus_paraxial
from .system import OpticalSystem


def _get(sysm: OpticalSystem, var: dict) -> float:
    s = sysm.surfaces[var["surface"]]
    p = var["param"]
    if p in ("curvature", "radius"):
        return s.curvature
    if p == "thickness":
        return s.thickness
    if p == "conic":
        return s.conic
    if p.upper().startswith("A"):
        i = (int(p[1:]) - 4) // 2
        return s.aspheric[i] if i < len(s.aspheric) else 0.0
    raise KeyError(p)


def _set(sysm: OpticalSystem, var: dict, v: float) -> None:
    s = sysm.surfaces[var["surface"]]
    p = var["param"]
    if "min" in var:
        v = max(v, var["min"])
    if "max" in var:
        v = min(v, var["max"])
    if p in ("curvature", "radius"):
        s.curvature = v
    elif p == "thickness":
        s.thickness = v
    elif p == "conic":
        s.conic = v
    else:
        i = (int(p[1:]) - 4) // 2
        while len(s.aspheric) <= i:
            s.aspheric.append(0.0)
        s.aspheric[i] = v


@dataclass
class OptimizeResult:
    system: OpticalSystem
    merit_history: list[float]
    rms_spot_um: list[float]


class Optimizer:
    def __init__(self, system: OpticalSystem, variables: list[dict], targets: dict | None = None,
                 rings: int = 4, focus: str | None = None):
        self.base = system.copy()
        self.variables = variables
        self.targets = targets or {}
        self.focus = focus
        self.px, self.py = hexapolar(rings)
        self.penalty = 10.0 * max(first_order(system).ep_radius, 1.0)

    def apply(self, x: np.ndarray) -> OpticalSystem:
        s = self.base.copy()
        for v, xv in zip(self.variables, x):
            _set(s, v, float(xv))
        if self.focus == "paraxial":
            focus_paraxial(s)
        return s

    def residuals(self, x: np.ndarray) -> np.ndarray:
        s = self.apply(x)
        res = []
        try:
            ev = Evaluator(s)
        except (ValueError, ZeroDivisionError):
            return np.full(self._nres, self.penalty)
        wsum = sum(s.wavelength_weights)
        for f in s.fields:
            ch = ev.chief(f)
            for wl, w in zip(s.wavelengths, s.wavelength_weights):
                r = ev.trace(f, self.px, self.py, wl)
                sc = math.sqrt(w / wsum / len(s.fields) / len(self.px))
                ex = np.where(r.valid, r.P[:, 0] - ch.P[0, 0], self.penalty)
                ey = np.where(r.valid, r.P[:, 1] - ch.P[0, 1], self.penalty)
                res.append(sc * np.nan_to_num(ex, nan=self.penalty))
                res.append(sc * np.nan_to_num(ey, nan=self.penalty))
        if "efl" in self.targets:
            wt = self.targets.get("efl_weight", 1.0) * 1e-2
            res.append(np.array([wt * (ev.fo.efl - self.targets["efl"])]))
        out = np.concatenate(res)
        self._nres = out.size
        return out

    def run(self, iterations: int = 50, verbose: bool = False) -> OptimizeResult:
        x = np.array([_get(self.base, v) for v in self.variables], dtype=float)
        r = self.residuals(x)
        merit = float(r @ r)
        hist = [merit]
        lam = 1e-3
        for it in range(iterations):
            J = np.empty((r.size, x.size))
            for i in range(x.size):
                h = 1e-7 * max(abs(x[i]), 1e-3)
                xp = x.copy()
                xp[i] += h
                J[:, i] = (self.residuals(xp) - r) / h
            JTJ = J.T @ J
            g = J.T @ r
            improved = False
            for _ in range(12):
                A = JTJ + lam * np.diag(np.diag(JTJ) + 1e-12)
                try:
                    dx = -np.linalg.solve(A, g)
                except np.linalg.LinAlgError:
                    lam *= 10
                    continue
                xn = x + dx
                rn = self.residuals(xn)
                mn = float(rn @ rn)
                if mn < merit:
                    x, r, merit = xn, rn, mn
                    lam = max(lam / 3, 1e-9)
                    improved = True
                    break
                lam *= 10
            hist.append(merit)
            if verbose:
                print(f"  iter {it + 1:3d}  merit = {merit:.6e}  λ = {lam:.1e}")
            if not improved or (len(hist) > 2 and hist[-2] - hist[-1] < 1e-10 * hist[-2]):
                break
        best = self.apply(x)
        ev = Evaluator(best)
        from .analysis import spot

        rms = [spot(ev, f).rms * 1e3 for f in best.fields]
        return OptimizeResult(best, hist, rms)


def optimize(system: OpticalSystem, config: dict | None = None, verbose: bool = False) -> OptimizeResult:
    cfg = config or system.optimization or {}
    if not cfg.get("variables"):
        raise ValueError("optimization.variables が指定されていません")
    opt = Optimizer(system, cfg["variables"], cfg.get("targets"), cfg.get("rings", 4), cfg.get("focus"))
    return opt.run(cfg.get("iterations", 50), verbose=verbose)
