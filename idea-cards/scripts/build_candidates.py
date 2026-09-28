#!/usr/bin/env python3
"""第4段階：extracted/*.json から candidates.csv を作る。

- UTF-8（BOM付き）
- 列：採否,ワード,種別,裏面テキスト,出典タイトル,URL,公開日,裏面の種類（採否は空欄）
- 公開日の古い順、同一記事内は抽出順
- dedupe.json（dedupe.py の出力）に載っているカードは除外する

既に candidates.csv があり採否が記入済みの場合は、同じ（ワード, URL）の行の採否を引き継ぐ。
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "candidates.csv"
HEADER = ["採否", "ワード", "種別", "裏面テキスト", "出典タイトル", "URL", "公開日", "裏面の種類"]


def main():
    removed = set()
    dd = ROOT / "dedupe.json"
    if dd.exists():
        removed = {(r["file"], r["index"]) for r in json.loads(dd.read_text(encoding="utf-8"))}

    kept = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("採否", "").strip():
                    kept[(row["ワード"], row["URL"])] = row["採否"]

    arts = []
    for p in (ROOT / "extracted").glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        arts.append((d["published"], p.name, d))
    arts.sort()

    rows = []
    for published, name, d in arts:
        for i, c in enumerate(d["cards"]):
            if (name, i) in removed:
                continue
            rows.append([
                kept.get((c["word"], d["url"]), ""),
                c["word"], c["type"], c["back"], d["title"], d["url"], published, c["back_kind"],
            ])

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    print(f"candidates.csv: {len(rows)}件 / {len(arts)}記事")


if __name__ == "__main__":
    main()
