#!/usr/bin/env python3
"""第1段階：noteの記事を取得し、articles/ にプレーンテキスト（Markdown見出し）で保存する。

使い方:
    python3 scripts/fetch_articles.py            # 未取得の記事だけ取得
    python3 scripts/fetch_articles.py --refresh  # 既存ファイルも取り直す

- 一覧: https://note.com/api/v2/creators/{user}/contents?kind=note&page={n}
    data.contents[] の name / key / price / publishAt / noteUrl、data.isLastPage を使う
- 本文: https://note.com/api/v3/notes/{key}
    data.body（HTML）、data.price、data.publish_at、data.note_url を使う
- 有料記事（price > 0）と、本文300字未満の記事は保存しない
- 判定結果は articles/_index.json に記録する（第2段階と報告で使う）
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

USER = "beefbowl60"
LIST_URL = "https://note.com/api/v2/creators/{user}/contents?kind=note&page={page}"
NOTE_URL = "https://note.com/api/v3/notes/{key}"
INTERVAL = 1.2  # 秒。アクセス間隔は1秒以上
MIN_CHARS = 300

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
INDEX = ARTICLES / "_index.json"

_last_request = 0.0


def get_json(url):
    global _last_request
    wait = INTERVAL - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (idea-cards personal backup)"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                _last_request = time.time()
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            _last_request = time.time()
            if attempt == 3:
                raise
            print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(2 ** (attempt + 1))


class NoteHTML(HTMLParser):
    """noteの本文HTMLをプレーンテキストに変換する。見出しは # 記法、画像は捨ててキャプションだけ残す。"""

    BLOCKS = {"p", "div", "li", "blockquote", "pre", "figcaption", "tr"}
    HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self.buf = []
        self.prefix = ""
        self.skip = 0

    def flush(self):
        text = "".join(self.buf)
        text = re.sub(r"[ \t　]+\n", "\n", text).strip()
        if text:
            self.lines.append(self.prefix + text)
        self.buf = []
        self.prefix = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in self.HEADINGS:
            self.flush()
            self.prefix = self.HEADINGS[tag] + " "
        elif tag == "li":
            self.flush()
            self.prefix = "- "
        elif tag == "blockquote":
            self.flush()
        elif tag == "figcaption":
            self.flush()
            self.prefix = "（画像キャプション）"
        elif tag in self.BLOCKS:
            self.flush()
        elif tag == "br":
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        elif tag in self.HEADINGS or tag in self.BLOCKS:
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)

    def text(self):
        self.flush()
        return "\n\n".join(self.lines)


def html_to_text(body_html):
    p = NoteHTML()
    p.feed(body_html or "")
    p.close()
    return html.unescape(p.text())


def count_chars(text):
    """本文文字数：見出し記号・キャプション表示・空白を除いた文字数。"""
    t = re.sub(r"^#+ ", "", text, flags=re.M)
    t = t.replace("（画像キャプション）", "")
    return len(re.sub(r"\s", "", t))


def list_all():
    items, page = [], 1
    while True:
        d = get_json(LIST_URL.format(user=USER, page=page))["data"]
        items.extend(d["contents"])
        print(f"list page {page}: {len(d['contents'])} items (total {d.get('totalCount')})")
        if d.get("isLastPage") or not d["contents"]:
            return items
        page += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="既存の記事ファイルも取り直す")
    args = ap.parse_args()
    ARTICLES.mkdir(parents=True, exist_ok=True)

    old = {}
    if INDEX.exists():
        old = {r["key"]: r for r in json.loads(INDEX.read_text(encoding="utf-8"))}

    index = []
    for it in list_all():
        key = it["key"]
        rec = {
            "key": key,
            "title": it["name"],
            "url": it.get("noteUrl") or f"https://note.com/{USER}/n/{key}",
            "published": (it.get("publishAt") or "")[:10],
            "price": it.get("price") or 0,
            "type": it.get("type"),
        }
        if rec["price"] > 0:
            rec["status"] = "paid"
            index.append(rec)
            continue

        prev = old.get(key)
        if prev and not args.refresh and prev.get("status") in ("ok", "short"):
            path = ARTICLES / prev["file"] if prev.get("file") else None
            if prev["status"] == "short" or (path and path.exists()):
                index.append(prev)
                continue

        d = get_json(NOTE_URL.format(key=key))["data"]
        price = d.get("price") or 0
        rec["published"] = (d.get("publish_at") or rec["published"])[:10]
        rec["url"] = d.get("note_url") or rec["url"]
        if price > 0:
            rec.update(price=price, status="paid")
            index.append(rec)
            continue
        text = html_to_text(d.get("body"))
        chars = count_chars(text)
        rec["chars"] = chars
        if chars < MIN_CHARS:
            rec["status"] = "short"
            index.append(rec)
            print(f"  short ({chars}): {rec['title']}")
            continue

        fname = f"{rec['published']}_{key}.md"
        front = (
            "---\n"
            f"title: {rec['title']}\n"
            f"url: {rec['url']}\n"
            f"published: {rec['published']}\n"
            f"chars: {chars}\n"
            "---\n\n"
        )
        (ARTICLES / fname).write_text(front + text + "\n", encoding="utf-8")
        rec.update(status="ok", file=fname)
        index.append(rec)
        print(f"  saved {fname} ({chars}字) {rec['title']}")

    index.sort(key=lambda r: (r["published"], r["key"]))
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    n = {s: sum(r["status"] == s for r in index) for s in ("ok", "short", "paid")}
    print(f"done: 全{len(index)}件 / 有料{n['paid']} / 300字未満{n['short']} / 保存{n['ok']}")


if __name__ == "__main__":
    main()
