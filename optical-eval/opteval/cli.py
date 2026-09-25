"""コマンドライン:  python -m opteval {info,report,optimize} lens.json"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analysis import Evaluator
from .system import OpticalSystem


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="opteval", description="光学設計評価ツール")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info", help="レンズデータ・一次量・収差係数・結像性能を表示")
    p.add_argument("lens")
    p = sub.add_parser("report", help="評価図 (PNG) と HTML レポートを出力")
    p.add_argument("lens")
    p.add_argument("-o", "--outdir", default="report")
    p = sub.add_parser("optimize", help="レンズファイルの optimization 設定に従って最適化")
    p.add_argument("lens")
    p.add_argument("-o", "--output", required=True, help="最適化後のレンズファイル (JSON)")
    p.add_argument("-n", "--iterations", type=int)
    args = ap.parse_args(argv)

    from . import report

    system = OpticalSystem.load(args.lens)
    if args.cmd == "info":
        print(report.text_report(Evaluator(system)))
    elif args.cmd == "report":
        ev = Evaluator(system)
        out = Path(args.outdir)
        paths = report.save_figures(ev, out)
        (out / "report.txt").write_text(report.text_report(ev) + "\n", encoding="utf-8")
        (out / "report.html").write_text(report.html_report(ev), encoding="utf-8")
        print(f"wrote {len(paths)} figures, report.txt, report.html -> {out}/")
    elif args.cmd == "optimize":
        from .optimize import optimize

        cfg = dict(system.optimization or {})
        if args.iterations:
            cfg["iterations"] = args.iterations
        res = optimize(system, cfg, verbose=True)
        res.system.save(args.output)
        print(f"merit: {res.merit_history[0]:.4e} -> {res.merit_history[-1]:.4e}")
        print("RMS spot [µm]: " + ", ".join(f"{v:.3f}" for v in res.rms_spot_um))
        print(f"saved -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
