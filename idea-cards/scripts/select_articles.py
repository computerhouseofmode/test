#!/usr/bin/env python3
"""第2段階：対象記事の選定と抽出件数の配分。

articles/_index.json（fetch_articles.py の出力）を読み、
- 本文の長さで1記事あたりの件数を決める（各区分の幅の中で、長いほど多く）
    〜2000字: 5〜7件 / 2001〜5000字: 8〜11件 / 5001字〜: 12〜15件
- 既定では対象記事をすべて使う（合計は MIN_TOTAL 以上あればよい）
- MAX_TOTAL を設定した場合のみ、合計がそれを超えるとき公開日順に等間隔で記事を選び、MAX_TOTAL に最も近くなるようにする
結果を selection.json と selection.md に書き出す。
"""
import json
from pathlib import Path

MIN_TOTAL = 1000  # 目安。下回った場合は報告する
MAX_TOTAL = None  # 上限を設けて絞り込むときだけ数値を入れる
BANDS = [  # (下限字数, 上限字数, 最小件数, 最大件数)
    (300, 2000, 5, 7),
    (2001, 5000, 8, 11),
    (5001, 10000, 12, 15),
]

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "articles" / "_index.json"


def allocate(chars):
    for lo, hi, nmin, nmax in BANDS:
        if chars <= hi or hi == BANDS[-1][1]:
            ratio = min(max((chars - lo) / (hi - lo), 0), 1)
            return round(nmin + ratio * (nmax - nmin))
    raise ValueError(chars)


def evenly(n, total):
    if n == 1:
        return [total // 2]
    return sorted({round(i * (total - 1) / (n - 1)) for i in range(n)})


def main():
    arts = [r for r in json.loads(INDEX.read_text(encoding="utf-8")) if r["status"] == "ok"]
    arts.sort(key=lambda r: (r["published"], r["key"]))
    for r in arts:
        r["alloc"] = allocate(r["chars"])

    if MAX_TOTAL is None or sum(r["alloc"] for r in arts) <= MAX_TOTAL:
        chosen = arts
    else:
        best = None
        for n in range(1, len(arts) + 1):
            idx = evenly(n, len(arts))
            s = sum(arts[i]["alloc"] for i in idx)
            if best is None or abs(s - MAX_TOTAL) < abs(best[0] - MAX_TOTAL):
                best = (s, idx)
        chosen = [arts[i] for i in best[1]]

    out = [{k: r[k] for k in ("file", "title", "url", "published", "chars", "alloc")} for r in chosen]
    (ROOT / "selection.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(r["alloc"] for r in out)
    lines = [
        "# 選定記事一覧",
        "",
        f"対象{len(arts)}記事から{len(out)}記事を選定 / 見込み総件数 {total}件",
        "",
        "| # | 公開日 | タイトル | 字数 | 配分 |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(out, 1):
        title = r["title"].replace("|", "｜")
        lines.append(f"| {i} | {r['published']} | {title} | {r['chars']} | {r['alloc']} |")
    (ROOT / "selection.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"選定 {len(out)}/{len(arts)} 記事, 見込み {total} 件")
    if total < MIN_TOTAL:
        print(f"注意: 見込み総件数が {MIN_TOTAL} 件に届いていません")


if __name__ == "__main__":
    main()
