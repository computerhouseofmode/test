#!/usr/bin/env python3
"""candidates.csv のうち採否が「○」「〇」「o」「1」「y」の行だけを cards.csv に書き出す。

出力列：ワード,種別,裏面テキスト,出典タイトル,URL,公開日,裏面の種類（UTF-8 BOM付き）
実行時に採用枚数と記事数を表示する。
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "candidates.csv"
OUT = ROOT / "cards.csv"
ACCEPT = {"○", "〇", "o", "1", "y"}
COLUMNS = ["ワード", "種別", "裏面テキスト", "出典タイトル", "URL", "公開日", "裏面の種類"]


def main():
    with SRC.open(encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("採否") or "").strip() in ACCEPT]

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r[c] for c in COLUMNS])

    print(f"採用 {len(rows)}枚 / {len({r['URL'] for r in rows})}記事 → {OUT.name}")


if __name__ == "__main__":
    main()
