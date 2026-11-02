# ドキュメントの生成

このサイトは [MkDocs](https://www.mkdocs.org/)（Material テーマ）と [mkdocstrings](https://mkdocstrings.github.io/) で、`docs/*.md` から生成しています。現在このリポジトリに Python コードはありませんが、追加したときに docstring からコードリファレンスを作れるよう mkdocstrings を入れたままにしています。

## 手元で見る

```
python3 -m venv .venv-docs
.venv-docs/bin/pip install -r requirements-docs.txt
.venv-docs/bin/mkdocs serve        # http://127.0.0.1:8000 でプレビュー
.venv-docs/bin/mkdocs build        # site/ に静的 HTML を出力
```

`site/` はそのまま開ける HTML なので、NAS に置いたり ZIP で共有したりできます。PDF が必要なときは、ブラウザの印刷機能で PDF に保存してください。

## 書き方のルール

- Python の関数やモジュールには Google スタイルの docstring を書く（`Args:`、`Returns:`、`Raises:`）
- 新しい Python モジュールを追加したら、`mkdocs.yml` の mkdocstrings に `paths: [<ディレクトリ>]` を足し、`docs/reference/` にページを作って `::: モジュール名` と書き、`nav` に追加する
- 仕様や API を変えたら、同じ PR で `docs/` も更新する
- 新しいページは `mkdocs.yml` の `nav` の該当する区分（はじめに・仕様書・導入手順・仕組みの解説・運用・開発者向け）に入れる
- 別のページの見出しにリンクするときは、見出しの末尾に `{#英字のid}` を付けて `[説明](spec.md#s3)` のように書く（日本語の見出しは自動の id が付かないため）。「spec.md 10章」のような文字だけの参照にはしない
- 新しい略語や専門用語は [用語集](glossary.md) に足す
- 実際の環境への作業は [構築記録](records.md) に日付と内容を書く
- `mkdocs build --strict` で、リンク切れがないことを確かめてから PR を出す
