#!/usr/bin/env python3
"""発想カードのツール（1ファイルのHTML）を作る。

cards.csv があればそれを、なければ candidates.csv を埋め込み、tool/hasso-cards.html に書き出す。
ブラウザで開くと3枚ランダムに表示される。ツール上で別の cards.csv を読み込むこともできる。
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "tool_template.html"
OUT = ROOT / "tool" / "hasso-cards.html"
COLUMNS = ["ワード", "種別", "裏面テキスト", "出典タイトル", "URL", "公開日", "裏面の種類"]


def main():
    src = ROOT / "cards.csv"
    label = "採用カード（cards.csv）"
    if not src.exists():
        src = ROOT / "candidates.csv"
        label = "カード候補（未選別）"
    with src.open(encoding="utf-8-sig", newline="") as f:
        rows = [[r[c] for c in COLUMNS] for r in csv.DictReader(f)]

    data = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("/*DATA*/[]", data, 1).replace('/*LABEL*/""', json.dumps(label, ensure_ascii=False), 1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {src.name} から {len(rows)}枚を埋め込み")


if __name__ == "__main__":
    main()
