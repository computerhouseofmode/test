"""光学系の定義（レンズデータ）と JSON 入出力。

面番号は CODE V と同様に  0 = OBJ,  1..n = 各面,  n+1 = IMG。
surfaces[i].thickness は面 i から面 i+1 までの距離、surfaces[i].material は
面 i と面 i+1 の間の媒質。
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .glass import FRAUNHOFER, refractive_index


def _parse_float(v) -> float:
    if v is None:
        return math.inf
    if isinstance(v, str):
        return math.inf if v.strip().lower() in ("inf", "infinity") else float(v)
    return float(v)


def _dump_float(v: float):
    return "inf" if math.isinf(v) else v


@dataclass
class Surface:
    radius: float = math.inf          # 曲率半径 [mm]（inf / 0 = 平面）
    thickness: float = 0.0            # 次面までの間隔 [mm]
    material: str = "AIR"             # 次面までの媒質
    semi_diameter: float | None = None  # 有効半径 [mm]。None なら自動計算（ケラレなし）
    conic: float = 0.0                # コーニック定数 k
    aspheric: list[float] = field(default_factory=list)  # [A4, A6, A8, ...]
    stop: bool = False                # 開口絞り
    comment: str = ""

    @property
    def curvature(self) -> float:
        if math.isinf(self.radius) or self.radius == 0:
            return 0.0
        return 1.0 / self.radius

    @curvature.setter
    def curvature(self, c: float) -> None:
        self.radius = math.inf if c == 0 else 1.0 / c

    @property
    def is_plane(self) -> bool:
        return self.curvature == 0 and not any(self.aspheric)

    def to_dict(self) -> dict:
        d = {"radius": _dump_float(self.radius), "thickness": _dump_float(self.thickness),
             "material": self.material}
        if self.semi_diameter is not None:
            d["semi_diameter"] = self.semi_diameter
        if self.conic:
            d["conic"] = self.conic
        if self.aspheric:
            d["aspheric"] = list(self.aspheric)
        if self.stop:
            d["stop"] = True
        if self.comment:
            d["comment"] = self.comment
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Surface":
        return cls(
            radius=_parse_float(d.get("radius", "inf")),
            thickness=_parse_float(d.get("thickness", 0.0)),
            material=str(d.get("material", "AIR")),
            semi_diameter=d.get("semi_diameter"),
            conic=float(d.get("conic", 0.0)),
            aspheric=[float(a) for a in d.get("aspheric", [])],
            stop=bool(d.get("stop", False)),
            comment=str(d.get("comment", "")),
        )


@dataclass
class OpticalSystem:
    surfaces: list[Surface]
    wavelengths: list[float] = field(
        default_factory=lambda: [FRAUNHOFER["F"], FRAUNHOFER["d"], FRAUNHOFER["C"]])
    wavelength_weights: list[float] | None = None
    primary: int = 1                  # 主波長のインデックス
    fields: list[float] = field(default_factory=lambda: [0.0])  # Y 方向の画角 [deg] または物体高 [mm]
    field_type: str = "angle"         # "angle" | "height"
    aperture_type: str = "EPD"        # "EPD" (入射瞳径) | "FNO" (無限物体) | "NAO" (物体側 NA)
    aperture_value: float = 10.0
    title: str = ""
    optimization: dict | None = None  # 最適化設定（任意）

    def __post_init__(self):
        if len(self.surfaces) < 3:
            raise ValueError("surfaces には OBJ, 少なくとも 1 面, IMG が必要です")
        if self.wavelength_weights is None:
            self.wavelength_weights = [1.0] * len(self.wavelengths)
        if self.field_type not in ("angle", "height"):
            raise ValueError("field_type must be 'angle' or 'height'")
        if self.aperture_type not in ("EPD", "FNO", "NAO"):
            raise ValueError("aperture_type must be EPD, FNO or NAO")

    # --- 基本プロパティ -------------------------------------------------
    @property
    def image_index(self) -> int:
        return len(self.surfaces) - 1

    @property
    def infinite_object(self) -> bool:
        return math.isinf(self.surfaces[0].thickness) or self.surfaces[0].thickness > 1e10

    @property
    def stop_index(self) -> int:
        for i, s in enumerate(self.surfaces[1:-1], start=1):
            if s.stop:
                return i
        return 1

    @property
    def primary_wavelength(self) -> float:
        return self.wavelengths[self.primary]

    @property
    def max_field(self) -> float:
        return max(abs(f) for f in self.fields)

    def index(self, i: int, wl: float) -> float:
        """面 i の後ろ（面 i と i+1 の間）の屈折率。"""
        return refractive_index(self.surfaces[i].material, wl)

    def vertex_positions(self) -> list[float]:
        """面 1 頂点を 0 とした各面頂点の z 座標（OBJ は除く / 無限遠なら nan）。"""
        z = [math.nan if self.infinite_object else -self.surfaces[0].thickness]
        acc = 0.0
        for s in self.surfaces[1:]:
            z.append(acc)
            acc += s.thickness
        return z

    def copy(self) -> "OpticalSystem":
        return copy.deepcopy(self)

    # --- 入出力 ---------------------------------------------------------
    def to_dict(self) -> dict:
        d = {
            "title": self.title,
            "wavelengths": self.wavelengths,
            "wavelength_weights": self.wavelength_weights,
            "primary": self.primary,
            "fields": {"type": self.field_type, "values": self.fields},
            "aperture": {"type": self.aperture_type, "value": self.aperture_value},
            "surfaces": [s.to_dict() for s in self.surfaces],
        }
        if self.optimization:
            d["optimization"] = self.optimization
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "OpticalSystem":
        wls = d.get("wavelengths", [FRAUNHOFER["F"], FRAUNHOFER["d"], FRAUNHOFER["C"]])
        wls = [FRAUNHOFER[w] if isinstance(w, str) else float(w) for w in wls]
        flds = d.get("fields", {"type": "angle", "values": [0.0]})
        ap = d.get("aperture", {"type": "EPD", "value": 10.0})
        return cls(
            surfaces=[Surface.from_dict(s) for s in d["surfaces"]],
            wavelengths=wls,
            wavelength_weights=d.get("wavelength_weights"),
            primary=int(d.get("primary", len(wls) // 2)),
            fields=[float(v) for v in flds["values"]],
            field_type=flds.get("type", "angle"),
            aperture_type=ap.get("type", "EPD").upper(),
            aperture_value=float(ap["value"]),
            title=d.get("title", ""),
            optimization=d.get("optimization"),
        )

    @classmethod
    def load(cls, path: str | Path) -> "OpticalSystem":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")
