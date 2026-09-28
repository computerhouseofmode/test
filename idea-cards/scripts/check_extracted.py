#!/usr/bin/env python3
"""extracted/*.json の形式チェック。引数なしなら全件、ファイル指定ならそのファイルだけ。

チェック内容：必須キー、種別・裏面の種類の値、裏面80〜150字、文カード20〜40字、
1記事2種類以上、配分件数との差、同一記事内の同一ワード、常体でない裏面（です・ます）。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TYPES = {"固有名詞", "概念", "文"}
KINDS = {"文脈", "辞書"}


def length(s):
    return len(re.sub(r"\s", "", s))


def check(path, alloc):
    warns = []
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"JSONとして読めない: {e}"]
    for k in ("title", "url", "published", "cards"):
        if k not in d:
            warns.append(f"キー {k} がない")
    cards = d.get("cards", [])
    words = set()
    for i, c in enumerate(cards, 1):
        w, t, b, bk = c.get("word", ""), c.get("type"), c.get("back", ""), c.get("back_kind")
        tag = f"#{i} {w[:20]}"
        if t not in TYPES:
            warns.append(f"{tag}: type={t}")
        if bk not in KINDS:
            warns.append(f"{tag}: back_kind={bk}")
        if not 80 <= length(b) <= 150:
            warns.append(f"{tag}: 裏面 {length(b)}字")
        if t == "文" and not 20 <= length(w) <= 40:
            warns.append(f"{tag}: 文 {length(w)}字")
        if re.search(r"(です|ます|でした|ました)[。、]", b):
            warns.append(f"{tag}: 裏面が敬体")
        if w in words:
            warns.append(f"{tag}: 同一記事内でワード重複")
        words.add(w)
    if len({c.get("type") for c in cards}) < 2:
        warns.append("種別が2種類未満")
    if alloc is not None and abs(len(cards) - alloc) > 1:
        warns.append(f"件数 {len(cards)}（配分 {alloc}）")
    return warns


def main():
    alloc = {}
    sel = ROOT / "selection.json"
    if sel.exists():
        alloc = {r["file"] + ".json": r["alloc"] for r in json.loads(sel.read_text(encoding="utf-8"))}
    paths = [Path(p) for p in sys.argv[1:]] or sorted((ROOT / "extracted").glob("*.json"))
    bad = 0
    for p in paths:
        w = check(p, alloc.get(p.name))
        if w:
            bad += 1
            print(f"{p.name}:")
            for x in w:
                print(f"  - {x}")
    print(f"checked {len(paths)} files, {bad} with warnings")


if __name__ == "__main__":
    main()
