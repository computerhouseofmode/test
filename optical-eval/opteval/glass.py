"""硝材データベース（Sellmeier 分散式）。波長の単位は µm。

屈折率は空気に対する相対屈折率として扱う（空気 = 1.0）。
材料名は以下のいずれか:
  * カタログ名 (例: "N-BK7", "F2", "SILICA")
  * モデルガラス "nd:vd" (例: "1.62:36.4")  … nd と Abbe 数から簡易分散を生成
  * 数値 (例: 1.5)                          … 無分散
"""

from __future__ import annotations

import math

# Fraunhofer 線 [µm]
FRAUNHOFER = {
    "g": 0.435835,
    "F": 0.4861327,
    "e": 0.546074,
    "d": 0.5875618,
    "C": 0.6562725,
}

# Sellmeier 係数 (B1, B2, B3, C1, C2, C3)   n^2 - 1 = Σ Bi λ^2 / (λ^2 - Ci)
SELLMEIER: dict[str, tuple[float, float, float, float, float, float]] = {
    "N-BK7": (1.03961212, 0.231792344, 1.01046945, 0.00600069867, 0.0200179144, 103.560653),
    "N-SK16": (1.34317774, 0.241144399, 0.994317969, 0.00704687339, 0.0229005000, 92.7508526),
    "F2": (1.34533359, 0.209073176, 0.937357162, 0.00997743871, 0.0470450767, 111.886764),
    "N-F2": (1.39757037, 0.159201403, 1.26865430, 0.00995906143, 0.0546931752, 119.248346),
    "N-SF5": (1.52481889, 0.187085527, 1.42729015, 0.0112547560, 0.0588995392, 129.141675),
    "N-SF11": (1.73759695, 0.313747346, 1.89878101, 0.0131887070, 0.0623068142, 155.236290),
    "N-BAF10": (1.58514950, 0.143559385, 1.08521269, 0.00926681282, 0.0424489805, 105.613573),
    "SILICA": (0.6961663, 0.4079426, 0.8974794, 0.0684043**2, 0.1162414**2, 9.896161**2),
    "CAF2": (0.5675888, 0.4710914, 3.8484723, 0.050263605**2, 0.1003909**2, 34.649040**2),
}
ALIASES = {"SK16": "N-SK16", "BK7": "N-BK7", "FUSED_SILICA": "SILICA", "F_SILICA": "SILICA"}
AIR_NAMES = {"", "AIR", "VACUUM"}


def _sellmeier(coef, wl: float) -> float:
    b1, b2, b3, c1, c2, c3 = coef
    w2 = wl * wl
    return math.sqrt(1.0 + b1 * w2 / (w2 - c1) + b2 * w2 / (w2 - c2) + b3 * w2 / (w2 - c3))


def _model_glass(nd: float, vd: float, wl: float) -> float:
    # Cauchy 型 n = A + B/λ^2 で nd と (nF - nC) = (nd - 1)/vd を満たす
    b = (nd - 1.0) / vd / (FRAUNHOFER["F"] ** -2 - FRAUNHOFER["C"] ** -2)
    a = nd - b / FRAUNHOFER["d"] ** 2
    return a + b / wl**2


def is_air(material) -> bool:
    return isinstance(material, str) and material.strip().upper() in AIR_NAMES


def refractive_index(material, wl: float) -> float:
    """材料 material の波長 wl [µm] における屈折率。"""
    if isinstance(material, (int, float)):
        return float(material)
    name = material.strip().upper()
    if name in AIR_NAMES:
        return 1.0
    name = ALIASES.get(name, name)
    if name in SELLMEIER:
        return _sellmeier(SELLMEIER[name], wl)
    if ":" in name:
        nd, vd = (float(v) for v in name.split(":"))
        return _model_glass(nd, vd, wl)
    try:
        return float(name)
    except ValueError:
        raise KeyError(f"未知の硝材です: {material}") from None


def abbe_number(material) -> float:
    nd = refractive_index(material, FRAUNHOFER["d"])
    nf = refractive_index(material, FRAUNHOFER["F"])
    nc = refractive_index(material, FRAUNHOFER["C"])
    return math.inf if nf == nc else (nd - 1.0) / (nf - nc)


def catalog() -> list[str]:
    return sorted(SELLMEIER)
