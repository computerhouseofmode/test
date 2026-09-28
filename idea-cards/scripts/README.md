# 発想カード作成スクリプト

`idea-cards/` で実行する。記事を追加したときは 1 から順に再実行する（取得済み記事・抽出済みJSONはスキップされる）。

1. `python3 scripts/fetch_articles.py` — noteから記事を取得し `articles/` に保存（有料・300字未満は除外。`--refresh` で取り直し）
2. `python3 scripts/select_articles.py` — 抽出件数を配分し `selection.json` / `selection.md` を作成
3. 新しい記事について `EXTRACTION_GUIDE.md` に従って `extracted/{記事ファイル名}.json` を作成（Claude Codeに依頼）
   - `python3 scripts/check_extracted.py` — 形式チェック
   - `python3 scripts/dedupe.py` — 記事をまたいだ同一ワードを最大3枚に制限（削る対象を `dedupe.json` に記録）
4. `python3 scripts/build_candidates.py` — `candidates.csv` を作成（記入済みの採否は引き継ぐ）
5. `candidates.csv` の採否列に ○ / 〇 / o / 1 / y を記入し、`python3 scripts/finalize.py` で `cards.csv` を作成
6. `python3 scripts/build_tool.py` — 発想カードのツール `tool/hasso-cards.html` を作成（cards.csv があればそれを、なければ候補を埋め込む）

`articles/` は記事本文のローカル保存のみで、git管理から除外している。
