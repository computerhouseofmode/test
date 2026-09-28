#!/usr/bin/env python3
"""第3段階の仕上げ：記事をまたいだ同一ワードを最大3枚に制限する。

extracted/*.json を読み、表記ゆれ（全角半角・空白・括弧）を正規化して同じになるワードを「同一ワード」とみなす。
4枚以上あるワードは、裏面テキストの内容が互いに最も異なる3枚を残す
（文字bigramのJaccard類似度で、残す3枚の類似度の合計が最小になる組み合わせ）。
削る対象は dedupe.json に書き出す（extracted/ の JSON は書き換えない）。build_candidates.py がこれを読んで除外する。
"""
import itertools
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

MAX_PER_WORD = 3
ROOT = Path(__file__).resolve().parent.parent


def norm(word):
    w = unicodedata.normalize("NFKC", word)
    w = re.sub(r"[\s『』「」【】（）()〈〉＜＞<>“”\"'・]", "", w)
    return w.lower()


def bigrams(s):
    s = re.sub(r"\s", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def sim(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def main():
    groups = defaultdict(list)
    for p in sorted((ROOT / "extracted").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for i, c in enumerate(d["cards"]):
            groups[norm(c["word"])].append({"file": p.name, "index": i, "word": c["word"], "back": c["back"]})

    removed = []
    for key, cards in groups.items():
        if len(cards) <= MAX_PER_WORD:
            continue
        bg = [bigrams(c["back"]) for c in cards]
        best = min(
            itertools.combinations(range(len(cards)), MAX_PER_WORD),
            key=lambda ix: sum(sim(bg[a], bg[b]) for a, b in itertools.combinations(ix, 2)),
        )
        for i, c in enumerate(cards):
            if i not in best:
                removed.append({"file": c["file"], "index": c["index"], "word": c["word"]})
        print(f"{cards[0]['word']}: {len(cards)}枚 → {MAX_PER_WORD}枚")

    (ROOT / "dedupe.json").write_text(json.dumps(removed, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"重複調整で削る件数: {len(removed)}")


if __name__ == "__main__":
    main()
