"""opteval — CODE V 風の光学設計評価ツール（逐次面・回転対称系）。"""

from .analysis import Evaluator
from .paraxial import first_order, focus_paraxial, seidel
from .system import OpticalSystem, Surface

__all__ = ["Evaluator", "OpticalSystem", "Surface", "first_order", "focus_paraxial", "seidel"]
__version__ = "0.1.0"
