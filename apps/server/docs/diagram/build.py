"""サーバー側の構成図(ロゴつき)を作る。

出力
  ../architecture.svg  : README に貼るスタンドアロンの SVG(ライト・ダークに自動で追従する)
  --html <path>        : アーティファクト用の HTML(同じ図に、決めたことの表を添える)

使い方: python3 apps/server/docs/diagram/build.py [--html <出力先>]

ロゴは ./logos/ に置いた SVG をそのまま読み込む(値は書き換えない。id の付け替えと、class の style 化だけ)。
  - TypeScript・Hono・PostgreSQL・Docker・Android・Kotlin・ONNX・Zod・Node.js: Simple Icons 16.38.0(CC0)
  - Lambda・API Gateway・S3・RDS: AWS Architecture Icons(2026-07-31 版)。AWS の利用ガイドラインに従い、色や形を変えない
  - SeaweedFS: 公式リポジトリの note/icon.svg(Apache-2.0)
WorkManager には専用のロゴが無いので、文字だけで示す(ロゴを作らない)。
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOGOS = HERE / "logos"
W, H = 1200, 780

# ---- 色(ライト・ダーク)。SVG の class と、アーティファクトのページで同じ名前を使う ----
LIGHT = {
    "bg": "#F5F7FA", "lane": "#ECF0F5", "card": "#FFFFFF", "line": "#D3DAE3", "line-strong": "#8995A6",
    "fg": "#18222F", "fg-muted": "#55627A", "accent": "#08746E", "tile": "#FFFFFF", "tile-line": "#D3DAE3",
    "ok": "#14633C", "ok-bg": "#D6F0E1", "plan": "#6E5200", "plan-bg": "#F5E6BE",
}
DARK = {
    "bg": "#10151C", "lane": "#18202A", "card": "#212B37", "line": "#2E3A49", "line-strong": "#74839A",
    "fg": "#E9EEF4", "fg-muted": "#A5B1C2", "accent": "#52D6C9", "tile": "#F2F5F9", "tile-line": "#3A4758",
    "ok": "#7FE3AB", "ok-bg": "#1C3A2B", "plan": "#F1CD72", "plan-bg": "#3B3115",
}
FONT = "'Noto Sans JP', 'Hiragino Sans', 'Yu Gothic', system-ui, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"


def token_css(tokens: dict[str, str]) -> str:
    return ";".join(f"--{k}:{v}" for k, v in tokens.items())


CLASS_CSS = f"""
.bg{{fill:var(--bg)}}
.lane{{fill:var(--lane);stroke:var(--line)}}
.card{{fill:var(--card);stroke:var(--line-strong);stroke-width:1.5}}
.card-plan{{fill:var(--card);stroke:var(--line-strong);stroke-width:1.5;stroke-dasharray:6 5}}
.tile{{fill:var(--tile);stroke:var(--tile-line)}}
.t{{fill:var(--fg);font-family:{FONT}}}
.t-m{{fill:var(--fg-muted)}}
.t-b{{font-weight:700}}
.t-acc{{fill:var(--accent)}}
.mono{{font-family:{MONO}}}
.ln{{stroke:var(--line-strong);stroke-width:2;fill:none}}
.ln-acc{{stroke:var(--accent);stroke-width:3.5;fill:none}}
.dash{{stroke-dasharray:7 6}}
.mk{{fill:var(--line-strong)}}
.mk-acc{{fill:var(--accent)}}
.pill-ok{{fill:var(--ok-bg)}}
.pill-ok-t{{fill:var(--ok);font-family:{FONT};font-weight:700}}
.pill-plan{{fill:var(--plan-bg)}}
.pill-plan-t{{fill:var(--plan);font-family:{FONT};font-weight:700}}
""".strip()


# ---- ロゴの読み込み ----
def _prefix_ids(body: str, prefix: str) -> str:
    """参照されている id だけ、前に prefix を付ける。参照されない id は外す(重複を避ける)。"""
    refs = set(re.findall(r"url\(#([^)]+)\)", body)) | set(re.findall(r'href="#([^"]+)"', body))
    def repl(m: re.Match[str]) -> str:
        return f'id="{prefix}{m.group(1)}"' if m.group(1) in refs else ""
    body = re.sub(r'id="([^"]+)"', repl, body)
    for r in refs:
        body = body.replace(f"url(#{r})", f"url(#{prefix}{r})").replace(f'href="#{r}"', f'href="#{prefix}{r}"')
    return body


def load_simple(name: str, hex_color: str) -> tuple[str, str]:
    s = (LOGOS / f"{name}.svg").read_text(encoding="utf-8")
    vb = re.search(r'viewBox="([^"]+)"', s).group(1)  # type: ignore[union-attr]
    paths = re.findall(r'<path d="([^"]+)"', s)
    return vb, "".join(f'<path d="{d}" fill="#{hex_color}"/>' for d in paths)


def load_full(name: str, prefix: str) -> tuple[str, str]:
    """色つきで描かれたロゴ(AWS・SeaweedFS)。class の style は、要素の style 属性に直す。"""
    s = (LOGOS / f"{name}.svg").read_text(encoding="utf-8")
    vb = re.search(r'viewBox="([^"]+)"', s).group(1)  # type: ignore[union-attr]
    body = re.sub(r"^.*?<svg[^>]*>", "", s, flags=re.S)
    body = re.sub(r"</svg>\s*$", "", body.strip())
    body = re.sub(r"<title>.*?</title>", "", body, flags=re.S)
    rules = {m.group(1): re.sub(r"\s+", " ", m.group(2)).strip()
             for m in re.finditer(r"\.(cls-\d+)\s*\{([^}]*)\}", body)}
    body = re.sub(r"<style>.*?</style>", "", body, flags=re.S)
    for cls, decl in rules.items():
        body = body.replace(f'class="{cls}"', f'style="{decl}"')
    return vb, _prefix_ids(body, prefix)


SIMPLE = {"typescript": "3178C6", "hono": "E36002", "postgresql": "4169E1", "docker": "2496ED", "android": "3DDC84",
          "kotlin": "7F52FF", "onnx": "005CED", "zod": "408AFF", "nodedotjs": "5FA04E"}
FULL = ["aws-lambda", "aws-api-gateway", "aws-s3", "aws-rds", "seaweedfs"]


def defs_svg() -> str:
    parts = ['<marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="mk"/></marker>',
             '<marker id="ah-acc" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="13" markerHeight="13" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="mk-acc"/></marker>']
    for name, hx in SIMPLE.items():
        vb, inner = load_simple(name, hx)
        parts.append(f'<symbol id="L-{name}" viewBox="{vb}">{inner}</symbol>')
    for name in FULL:
        vb, inner = load_full(name, f"{name}-")
        parts.append(f'<symbol id="L-{name}" viewBox="{vb}">{inner}</symbol>')
    return "<defs>" + "".join(parts) + "</defs>"


# ---- 描画の部品 ----
def esc(s: str) -> str:
    return html.escape(s, quote=False)


def text(x: float, y: float, s: str, size: float = 13, cls: str = "t", anchor: str = "start") -> str:
    return f'<text x="{x}" y="{y}" font-size="{size}" class="{cls}" text-anchor="{anchor}">{esc(s)}</text>'


def logo(name: str, x: float, y: float, size: float, tile: bool = True) -> str:
    """Simple Icons 系は、白いタイルの上に 64% の大きさで置く(ダークでも色が読める)。AWS・SeaweedFS はそのまま(AWS は色も形も変えない)。"""
    if name.startswith("aws-"):
        return f'<use href="#L-{name}" x="{x}" y="{y}" width="{size}" height="{size}"/>'
    pad = size * 0.18
    out = f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="{size * 0.2:.1f}" class="tile"/>' if tile else ""
    return out + f'<use href="#L-{name}" x="{x + pad:.1f}" y="{y + pad:.1f}" width="{size - 2 * pad:.1f}" height="{size - 2 * pad:.1f}"/>'


def card(x: float, y: float, w: float, h: float, plan: bool = False) -> str:
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" class="{"card-plan" if plan else "card"}"/>'


def arrow(d: str, accent: bool = False, plan: bool = False) -> str:
    cls = ("ln-acc" if accent else "ln") + (" dash" if plan else "")
    return f'<path d="{d}" class="{cls}" marker-end="url(#{"ah-acc" if accent else "ah"})"/>'


def pill(x: float, y: float, label: str, kind: str) -> str:
    w = 14 * len(label) + 20
    return (f'<rect x="{x}" y="{y}" width="{w}" height="24" rx="12" class="pill-{kind}"/>'
            f'<text x="{x + w / 2}" y="{y + 16.5}" font-size="12.5" class="pill-{kind}-t" text-anchor="middle">{esc(label)}</text>')


def lines(x: float, y: float, rows: list[str], size: float = 12.5, gap: float = 19, cls: str = "t t-m") -> str:
    return "".join(text(x, y + i * gap, r, size, cls) for i, r in enumerate(rows))


def diagram_body(with_title: bool) -> str:
    o: list[str] = []
    o.append(f'<rect width="{W}" height="{H}" class="bg"/>')
    if with_title:
        o.append(text(24, 36, "サーバー側の構成", 19, "t t-b"))
        o.append(text(W - 24, 36, "2026-11-18 時点", 13, "t t-m", "end"))

    # --- レーン ---
    o.append(f'<rect x="20" y="58" width="{W - 40}" height="332" rx="14" class="lane"/>')
    o.append(text(304, 90, "いまの構成：ローカル", 15, "t t-b"))
    o.append(pill(464, 72, "動作確認済み", "ok"))
    o.append(text(W - 44, 90, "PostgreSQL と SeaweedFS は Docker Compose で起動。API は Node.js（npm run dev）", 12, "t t-m", "end"))
    o.append(f'<rect x="20" y="418" width="{W - 40}" height="338" rx="14" class="lane"/>')
    o.append(text(304, 450, "本番：AWS", 15, "t t-b"))
    o.append(pill(394, 432, "未構築（計画）", "plan"))

    # --- Android アプリ（2 つのレーンにまたがる。同じアプリ） ---
    o.append(card(44, 104, 236, 626))
    o.append(logo("android", 60, 120, 44))
    o.append(text(114, 140, "Android アプリ", 15, "t t-b"))
    o.append(text(114, 160, "apps/detector-android", 11.5, "t t-m mono"))
    items = [
        ("kotlin", "Kotlin", ["センサーと GPS を受け取り、", "2 秒の窓ごとに特徴量にする"]),
        ("onnx", "ONNX Runtime", ["端末の中で判定する", "（flat・step・rough）"]),
        (None, "端末に残す", ["判定結果を 1 件ずつファイルに", "書き、送れた件数を持つ"]),
        (None, "WorkManager", ["走行後、Wi-Fi のときだけ", "生データを送る（失敗は再試行）"]),
    ]
    y = 200
    for lg, title, cap in items:
        if lg:
            o.append(logo(lg, 60, y, 36))
            tx = 106
        else:
            o.append(f'<rect x="60" y="{y}" width="4" height="36" rx="2" class="mk"/>')
            tx = 76
        o.append(text(tx, y + 15, title, 14, "t t-b"))
        o.append(text(tx, y + 33, cap[0], 12, "t t-m"))
        o.append(text(tx, y + 50, cap[1], 12, "t t-m"))
        y += 94

    # --- ローカル: API ---
    o.append(card(500, 112, 290, 150))
    for i, n in enumerate(["typescript", "hono", "nodedotjs", "zod"]):
        o.append(logo(n, 518 + i * 48, 126, 38))
    o.append(text(518, 196, "サーバー API", 15, "t t-b"))
    o.append(text(664, 196, "apps/server", 11.5, "t t-m mono"))
    o.append(lines(518, 218, ["共有キー（x-api-key）で認証し、", "Zod で入力を検証する"], 12.5, 19))
    # --- ローカル: DB・ストレージ ---
    o.append(card(900, 112, 260, 92))
    o.append(logo("postgresql", 916, 128, 44))
    o.append(text(970, 148, "PostgreSQL", 15, "t t-b"))
    o.append(text(970, 168, "走行・判定結果", 12.5, "t t-m"))
    o.append(logo("docker", 1114, 124, 30))
    o.append(card(900, 232, 260, 140))
    o.append(logo("seaweedfs", 916, 248, 44))
    o.append(text(970, 268, "SeaweedFS", 15, "t t-b"))
    o.append(text(970, 288, "S3 互換のストレージ", 12.5, "t t-m"))
    o.append(logo("docker", 1114, 244, 30))
    o.append(lines(916, 326, ["生データ（input.csv）を", "走行ごとに置く"], 12.5, 19))

    # --- ローカル: 矢印 ---
    o.append(arrow("M280,148 L498,148"))
    o.append(text(389, 140, "① 判定結果", 12.5, "t t-b", "middle"))
    o.append(text(389, 166, "5 秒ごと・位置つき", 11.5, "t t-m", "middle"))
    o.append(arrow("M280,208 L498,208"))
    o.append(text(389, 200, "② 署名付き URL を要求", 12.5, "t t-b", "middle"))
    o.append(arrow("M280,248 L498,248"))
    o.append(text(389, 240, "④ 完了を通知", 12.5, "t t-b", "middle"))
    o.append(arrow("M790,158 L898,158"))
    o.append(text(844, 150, "保存", 12.5, "t t-b", "middle"))
    o.append(arrow("M790,252 L898,252"))
    o.append(text(844, 244, "サイズ確認", 12.5, "t t-b", "middle"))
    # ③ 署名付き URL で直接 PUT（API を通さない）
    o.append(arrow("M280,318 L898,318", accent=True))
    o.append(text(589, 306, "③ input.csv を署名付き URL で直接 PUT（API を通さない）", 13.5, "t t-b t-acc", "middle"))
    o.append(text(589, 340, "50〜160 MB。Lambda は 6 MB までしか受けられないため", 12, "t t-m", "middle"))

    # --- 本番: API Gateway + Lambda ---
    o.append(card(500, 472, 290, 150, plan=True))
    o.append(logo("aws-api-gateway", 518, 488, 44))
    o.append(f'<path d="M570,510 L586,510" class="ln" marker-end="url(#ah)"/>')
    o.append(logo("aws-lambda", 592, 488, 44))
    o.append(text(518, 562, "API Gateway + Lambda", 15, "t t-b"))
    o.append(lines(518, 584, ["同じ Hono のコードに、", "Lambda 用の入口を足す"], 12.5, 19))
    o.append(card(900, 472, 260, 92, plan=True))
    o.append(logo("aws-rds", 916, 488, 44))
    o.append(text(970, 508, "RDS など", 15, "t t-b"))
    o.append(text(970, 528, "PostgreSQL（未選定）", 12.5, "t t-m"))
    o.append(card(900, 592, 260, 100, plan=True))
    o.append(logo("aws-s3", 916, 608, 44))
    o.append(text(970, 628, "Amazon S3", 15, "t t-b"))
    o.append(text(970, 648, "署名付き URL で受ける", 12.5, "t t-m"))

    # --- 本番: 矢印 ---
    o.append(arrow("M280,508 L498,508", plan=True))
    o.append(text(389, 500, "①②④ と同じ", 12.5, "t t-m", "middle"))
    o.append(arrow("M790,518 L898,518", plan=True))
    o.append(text(844, 510, "保存", 12.5, "t t-m", "middle"))
    o.append(arrow("M280,664 L898,664", accent=True, plan=True))
    o.append(text(589, 652, "③ 同じ手順で直接 PUT", 13.5, "t t-b t-acc", "middle"))
    o.append(text(500, 720, "ローカルで AWS を再現する AWS Emulator は、Lambda から PostgreSQL につながらないなどの理由で見送り", 12, "t t-m"))
    return "".join(o)


def standalone_svg() -> str:
    style = (f"<style>:root{{{token_css(LIGHT)}}}"
             f"@media (prefers-color-scheme: dark){{:root{{{token_css(DARK)}}}}}{CLASS_CSS}</style>")
    label = ("サーバー側の構成。Android アプリが判定結果を 5 秒ごとに API へ送り、生データは署名付き URL でストレージへ直接送る。"
             "上段はローカルで動作確認済み、下段は AWS の計画")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{label}">'
            f"<title>サーバー側の構成</title>{style}{defs_svg()}{diagram_body(True)}</svg>\n")


def inline_svg() -> str:
    label = ("Android アプリが判定結果を 5 秒ごとに API へ送り、生データは署名付き URL でストレージへ直接送る。"
             "上段はローカルで動作確認済み、下段は AWS の計画")
    # 見出しの分の余白(上の 48)は、ページ側に見出しがあるので削る
    return f'<svg viewBox="0 48 {W} {H - 48}" role="img" aria-label="{label}">{defs_svg()}{diagram_body(False)}</svg>'


# ---- アーティファクトの HTML ----
ROWS = [
    ("API", "TypeScript + Hono + Zod を Node.js で動かす（`npm run dev`）", "API Gateway + Lambda。Lambda 用の入口を足す",
     "静的型付けで書きたい。Hono は Lambda でも動く。Zod で、実行時にも入力の型を検証する"),
    ("DB", "PostgreSQL（Docker）", "RDS など（未選定）",
     "地図で範囲を検索し、同じ場所を何度も通った集計をするのに、SQL が素直"),
    ("生データの置き場", "SeaweedFS（Docker。S3 の API）", "Amazon S3",
     "50〜160 MB の生データを置く。S3 の API だけを使うので、そのまま入れ替えられる"),
    ("生データの送り方", "署名付き URL で、アプリから直接 PUT", "同じ",
     "Lambda は 6 MB を超えて受けられない。API を通さず、API は URL の発行と完了の確認だけをする"),
    ("判定結果の送り方", "5 秒ごとにまとめて POST。失敗したら端末に残して再送", "同じ",
     "(走行 ID, 窓の始まり) で重複を弾くので、再送しても二重にならない。flat も送る（誤検知を数えるため）"),
    ("認証", "共有キー（x-api-key）", "同じ（HTTPS にする）",
     "研究室の中だけの前提。キーはアプリに埋め込むので、強い認証ではない"),
    ("見送ったもの", "AWS Emulator、MinIO", "-",
     "AWS Emulator は Lambda から PostgreSQL につながらず、50〜160 MB も入らない。MinIO のコミュニティ版は、公式イメージの配布をやめ、リポジトリもアーカイブされた"),
]

PAGE_CSS = """
:root{%s;--bg-page:var(--bg)}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){%s;color-scheme:dark}}
:root[data-theme="dark"]{%s;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font-family:'Noto Sans JP','Hiragino Sans','Yu Gothic',system-ui,sans-serif;font-size:15px;line-height:1.7;
  padding-block:28px 56px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
main{max-width:1180px;margin-inline:auto;display:flex;flex-direction:column;gap:28px}
header{display:flex;flex-direction:column;gap:6px}
h1{font-size:28px;line-height:1.3;margin:0;text-wrap:balance;letter-spacing:.01em}
h2{font-size:18px;margin:0 0 10px;text-wrap:balance}
.lead{margin:0;color:var(--fg-muted);max-width:44em}
.meta{font-size:12.5px;color:var(--fg-muted);font-family:'JetBrains Mono',ui-monospace,Menlo,monospace}
figure{margin:0;display:flex;flex-direction:column;gap:10px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:14px;background:var(--bg)}
.scroll svg{display:block;min-width:900px;width:100%%;height:auto}
figcaption{font-size:13.5px;color:var(--fg-muted);max-width:60em}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%%;min-width:820px;font-size:14px}
th,td{text-align:left;vertical-align:top;padding:12px 14px;border-bottom:1px solid var(--line)}
th{font-size:12.5px;color:var(--fg-muted);font-weight:700;letter-spacing:.04em;background:var(--lane)}
tr:last-child td{border-bottom:0}
td:first-child{font-weight:700;white-space:nowrap}
td code{font-family:'JetBrains Mono',ui-monospace,Menlo,monospace;font-size:12.5px;background:var(--lane);padding:1px 6px;border-radius:4px}
.credits{font-size:12.5px;color:var(--fg-muted);max-width:60em;margin:0}
.credits a{color:var(--accent)}
""" + CLASS_CSS


def cell(c: str) -> str:
    """表のセル。`で囲んだ部分は、等幅のコードにする"""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(c, quote=False))


def html_page() -> str:
    css = PAGE_CSS % (token_css(LIGHT), token_css(DARK), token_css(DARK))
    rows = "".join("<tr>" + "".join(f"<td>{cell(c)}</td>" for c in r) + "</tr>" for r in ROWS)
    return f"""<title>サーバー構成図</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Noto+Sans+JP:wght@400;700&display=swap">
<style>{css}</style>
<main>
  <header>
    <div class="meta">road-irregularity-ml / apps/server・2026-11-18 時点</div>
    <h1>サーバー側の構成</h1>
    <p class="lead">スマホで判定した結果と、走行後の生データを、サーバーに送って残す。上段はローカルで動作確認まで済ませた構成、下段は本番の AWS に載せる計画。</p>
  </header>
  <figure>
    <div class="scroll">{inline_svg()}</div>
    <figcaption>番号は送る順番。①は走行中に何度も、②③④は走行を止めたあと。③だけは API を通らず、アプリがストレージへ直接送る（青緑の太い矢印）。</figcaption>
  </figure>
  <section>
    <h2>決めたことと、その理由</h2>
    <div class="tablewrap"><table>
      <thead><tr><th>項目</th><th>いま（ローカル）</th><th>本番（AWS・計画）</th><th>理由</th></tr></thead>
      <tbody>{rows}</tbody>
    </table></div>
  </section>
  <p class="credits">ロゴは各社・各プロジェクトのもので、構成を示す目的でだけ使っている。AWS のアイコンは <a href="https://aws.amazon.com/architecture/icons/" target="_blank" rel="noopener">AWS Architecture Icons</a>（2026-07-31 版。色と形は変えていない）。TypeScript・Hono・PostgreSQL・Docker・Android・Kotlin・ONNX・Zod・Node.js は <a href="https://simpleicons.org" target="_blank" rel="noopener">Simple Icons</a> 16.38.0（CC0）。SeaweedFS は公式リポジトリの <code>note/icon.svg</code>（Apache-2.0）。WorkManager は専用のロゴが無いので文字だけにしている。</p>
</main>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", type=Path, help="アーティファクト用の HTML の出力先")
    args = ap.parse_args()
    out = HERE.parent / "architecture.svg"
    out.write_text(standalone_svg(), encoding="utf-8")
    print("書き出し:", out.relative_to(HERE.parent.parent.parent.parent), f"({out.stat().st_size // 1024} KB)")
    if args.html:
        args.html.write_text(html_page(), encoding="utf-8")
        print("書き出し:", args.html)
