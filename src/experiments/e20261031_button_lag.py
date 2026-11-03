"""10.31 のデータで、ボタンを押してから段差・凸凹に着くまでのラグが、精度にどう効くかを調べる。

10.31 は、段差・凸凹を通過するたびに START〜STOP を押した(継続ボタンなし)。START を押してから
進み始めるので、区間の始めに、段差・凸凹に着く前の平坦な走行が入る。

1. ラグを波形から測る(モデルは使わない)
   通過ごとに、START から「揺れ始め」まで、「揺れの終わり」から STOP までの時間。
   揺れている = z の 100ms RMS 包絡線が、flat セッションの包絡線の 99 パーセンタイルを超える(10.17 と同じ)。
2. ラベルの区間を変えて、10 月上旬と同じ条件で評価する
   方針A(区間に窓の半分以上が重なる窓だけ使う。イベントのあるセッションの区間の外は捨てる)、xyz18 と m6、
   窓 1.0・2.0 秒(1/4 ずつずらす)、SVM・RF、セッション単位の LOGO。flat は flat 用の 2 セッション
   (ブロックに分けず、セッションを 1 グループにする)。
   取り消した通過(dansa_cancel)は区間にせず、その区間に少しでも重なる窓は捨てる。
   車椅子は、既定で standard(汎用)だけを使う。original(従来)は凸凹の揺れが明らかに大きく
   (e20261031_wheelchair_compare)、混ぜない。--wheelchair all で、混ぜた場合を参考に出せる。

区間の条件:
  pre0.5  : START の 0.5 秒前から(10 月上旬の既定。参考)
  button  : START〜STOP のまま
  shift_d : START を d 秒後ろにずらす(STOP はそのまま)
  activity: 通過ごとに、揺れ始め〜揺れの終わり(揺れが無い通過は使わない)

--exclude でセッションを除き、--flat-blocks で flat を時間のブロックに分けられる(静かな flat だけを使う評価など)。

出力(data/analysis/20261031_button_lag/<--wheelchair>[_<--tag>]/):
  passes.csv            : 通過ごとの長さ・ラグ
  lag_hist.png          : ラグの分布
  waveform_examples.png : 波形とボタンの区間・揺れ始め/終わり
  results.csv           : 条件ごとの精度・窓数
  confusion_counts.csv  : 条件ごとの混同行列
  recall_by_wheelchair.csv : 車椅子ごとの再現率
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from sklearn.metrics import balanced_accuracy_score
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.model_selection import cross_val_predict

from src.roadml.evaluation import DISPLAY
from src.roadml.evaluation import LABELS
from src.roadml.evaluation import models
from src.roadml.evaluation import summarize
from src.roadml.features import BASIC
from src.roadml.features import SHAPE
from src.roadml.features import axis_features
from src.roadml.features import cols
from src.roadml.io import GRAVITY_MPS2
from src.roadml.io import load_world_session
from src.roadml.labeling import compute_overlap_ratio

plt.rcParams["font.family"] = "Hiragino Sans"

ROOT = Path(__file__).resolve().parents[2]
FEATURES = cols("xyz", BASIC + SHAPE)
# 特徴量セット: xyz18(3 軸)と、m6(合成加速度 |a| − 重力のみ。姿勢に依存しない)。10.12 と同じ 2 つ
FEATURE_SETS = {"xyz18": FEATURES, "m6": cols("m", BASIC + SHAPE)}
WINDOWS_S = [1.0, 2.0]
SHIFTS_S = [0.25, 0.5, 1.0, 1.5]
ENV_S = 0.100  # 揺れの判定の包絡線(10.17 と同じ)
ACTIVE_PERCENTILE = 99.0
KIND_OF_FILE = {"dansa": "dansa", "dekobo": "dekobo"}


def load_session(run_dir: Path) -> dict:
    world = load_world_session(run_dir)
    ts = world["timestamp"].to_numpy(float)
    axes = {
        "x": world["accWorldX"].to_numpy(float),
        "y": world["accWorldY"].to_numpy(float),
        "z": world["accWorldZ"].to_numpy(float) - GRAVITY_MPS2,
        "m": world["accWorldMag"].to_numpy(float) - GRAVITY_MPS2,
    }
    fs = 1000.0 / np.median(np.diff(ts))
    env = np.sqrt(uniform_filter1d(axes["z"] ** 2, size=max(1, int(ENV_S * fs)), mode="nearest"))
    return {"ts": ts, "axes": axes, "fs": fs, "env": env}


def load_passes(run_dir: Path) -> pd.DataFrame:
    """通過(start〜stop)の一覧。段差は pass_id で対応づけ、取り消した通過は cancelled=True(区間は start〜取消)。"""
    rows = []
    for kind in ("dansa", "dekobo"):
        path = run_dir / f"{kind}.csv"
        if not path.exists():
            continue
        ev = pd.read_csv(path).sort_values("timestamp_ms")
        ev = ev[~ev["event"].str.endswith("_during")]
        if kind == "dansa":
            for pass_id, g in ev.groupby("pass_id"):
                at = {e: g.loc[g["event"] == f"dansa_{e}", "timestamp_ms"] for e in ("start", "stop", "cancel")}
                stop = g[g["event"] == "dansa_stop"]
                cancelled = len(at["cancel"]) > 0
                end = at["cancel"].iloc[0] if cancelled else at["stop"].iloc[0]
                sub = f"{g['direction'].iloc[0]}_{stop['pass_type'].iloc[0]}" if len(stop) else ""
                rows.append({"kind": kind, "pass_id": int(pass_id), "start_ms": float(at["start"].iloc[0]),
                             "stop_ms": float(end), "sub": sub.replace("_nan", ""), "cancelled": cancelled})
        else:
            starts = ev.loc[ev["event"] == "dekobo_start", "timestamp_ms"].to_numpy(float)
            stops = ev.loc[ev["event"] == "dekobo_stop", "timestamp_ms"].to_numpy(float)
            for i, (a, b) in enumerate(zip(starts, stops), start=1):
                rows.append({"kind": kind, "pass_id": i, "start_ms": a, "stop_ms": b, "sub": "rough",
                             "cancelled": False})
    return pd.DataFrame(rows)


def add_activity(passes: pd.DataFrame, sess: dict, threshold: float) -> pd.DataFrame:
    """通過ごとの揺れ始め・揺れの終わり(区間の中で包絡線が閾値を超えた最初と最後)。"""
    ts, env = sess["ts"], sess["env"]
    onset, offset = [], []
    for a, b in zip(passes["start_ms"], passes["stop_ms"]):
        m = (ts >= a) & (ts <= b) & (env > threshold)
        onset.append(ts[m][0] if m.any() else np.nan)
        offset.append(ts[m][-1] if m.any() else np.nan)
    return passes.assign(
        onset_ms=onset, offset_ms=offset,
        dur_s=(passes["stop_ms"] - passes["start_ms"]) / 1000.0,
        lag_start_s=(np.array(onset) - passes["start_ms"]) / 1000.0,
        lag_stop_s=(passes["stop_ms"] - np.array(offset)) / 1000.0,
    )


def window_features(sess: dict, window_s: float) -> pd.DataFrame:
    ts, fs = sess["ts"], sess["fs"]
    window_ms = window_s * 1000.0
    expected = window_ms / np.median(np.diff(ts))
    rows, start = [], ts[0]
    while start + window_ms <= ts[-1]:
        lo, hi = np.searchsorted(ts, [start, start + window_ms])
        if hi - lo >= 0.8 * expected:
            row = {"start_ms": start}
            for key, values in sess["axes"].items():
                row.update(axis_features(values[lo:hi], key, fs, window_s))
            rows.append(row)
        start += window_s * 250.0
    return pd.DataFrame(rows)


def intervals_for(passes: pd.DataFrame, condition: str) -> tuple[dict, list]:
    """条件ごとの、種類別の区間と、捨てる区間(取り消した通過)。"""
    ok = passes[~passes["cancelled"]]
    if condition == "pre0.5":
        a, b = ok["start_ms"] - 500.0, ok["stop_ms"]
    elif condition == "button":
        a, b = ok["start_ms"], ok["stop_ms"]
    elif condition.startswith("shift_"):
        a, b = ok["start_ms"] + float(condition.removeprefix("shift_")) * 1000.0, ok["stop_ms"]
    elif condition == "activity":
        a, b = ok["onset_ms"], ok["offset_ms"]
    else:
        raise ValueError(condition)
    keep = (a < b).to_numpy() & a.notna().to_numpy()
    intervals = {k: [] for k in KIND_OF_FILE}
    for kind, x, y in zip(ok["kind"][keep], a[keep], b[keep]):
        intervals[kind].append((float(x), float(y)))
    dropped = [(float(x), float(y)) for x, y in passes.loc[passes["cancelled"], ["start_ms", "stop_ms"]].to_numpy()]
    return intervals, dropped


def label_windows(win: pd.DataFrame, window_s: float, kind: str, intervals: dict, dropped: list) -> pd.Series:
    """方針A のラベル。イベントのあるセッションで、どの区間にも半分以上重ならない窓は None(捨てる)。"""
    if kind == "flat":
        return pd.Series("flat", index=win.index)
    labels = []
    for start in win["start_ms"]:
        end = start + window_s * 1000.0
        if dropped and compute_overlap_ratio(window_start_ms=start, window_end_ms=end, intervals=dropped) > 0:
            labels.append(None)
            continue
        label = None
        for k in ("dansa", "dekobo"):  # 既存パイプライン同様、dansa を優先
            if compute_overlap_ratio(window_start_ms=start, window_end_ms=end, intervals=intervals[k]) >= 0.5:
                label = k
                break
        labels.append(label)
    return pd.Series(labels, index=win.index)


def plot_lags(passes: pd.DataFrame, path: Path) -> None:
    ok = passes[~passes["cancelled"]]
    order = ["up_stop", "up_climb", "down", "rough"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, col, title in zip(axes, ["lag_start_s", "lag_stop_s"],
                              ["START → 揺れ始め [s]", "揺れの終わり → STOP [s]"]):
        data = [ok.loc[ok["sub"] == s, col].dropna() for s in order]
        ax.boxplot(data, tick_labels=[f"{s}\n(n={len(d)})" for s, d in zip(order, data)])
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_examples(cases: list, sessions: dict, passes: pd.DataFrame, threshold: float, path: Path) -> None:
    fig, axes = plt.subplots(len(cases), 1, figsize=(15, 2.8 * len(cases)))
    for ax, (s, t0, t1) in zip(axes, cases):
        sess = sessions[s]
        ts = sess["ts"]
        t = (ts - ts[0]) / 1000.0
        m = (t >= t0) & (t <= t1)
        ax.plot(t[m], sess["axes"]["z"][m], lw=0.4, color="black")
        ax.plot(t[m], sess["env"][m], lw=1.0, color="tab:orange")
        ax.axhline(threshold, color="red", ls="--", lw=0.8)
        for r in passes[passes["session"] == s].itertuples():
            x0, x1 = (r.start_ms - ts[0]) / 1000.0, (r.stop_ms - ts[0]) / 1000.0
            if x1 < t0 or x0 > t1:
                continue
            ax.axvspan(x0, x1, color="tab:blue" if r.kind == "dansa" else "tab:red", alpha=0.15)
            if not np.isnan(r.onset_ms):
                ax.axvline((r.onset_ms - ts[0]) / 1000.0, color="green", lw=1.0)
                ax.axvline((r.offset_ms - ts[0]) / 1000.0, color="purple", lw=1.0)
            ax.text(x0, 34, r.sub, fontsize=7)
        ax.set_xlim(t0, t1)
        ax.set_ylim(-40, 40)
        ax.set_title(s, fontsize=10)
    axes[-1].set_xlabel("時間 [s]（黒 z、橙 100ms RMS 包絡線、赤点線 揺れの閾値、背景 ボタンの区間、緑 揺れ始め、紫 揺れの終わり）")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def split_blocks(win: pd.DataFrame, n_blocks: int, window_s: float) -> pd.DataFrame:
    """flat のセッションを時間で n_blocks 個のグループに分ける(windows.build_run と同じ。境目の窓は捨てる)。"""
    start = win["start_ms"].to_numpy()
    edges = np.linspace(start.min(), start.max(), n_blocks + 1)
    block = np.clip(np.searchsorted(edges, start, side="right") - 1, 0, n_blocks - 1)
    near = np.min(np.abs(start[:, None] - edges[1:-1]), axis=1) < window_s * 1000.0
    return win.assign(group=[f"{g}_b{b}" for g, b in zip(win["group"], block)])[~near]


def evaluate(df: pd.DataFrame, features: list[str], model) -> tuple[np.ndarray, dict]:
    """3 クラスの評価と、step と rough だけで学習し直した 2 クラスの評価(sr_*)。r_* はクラスごとの再現率。"""
    pred = cross_val_predict(model, df[features], df["label"], groups=df["group"], cv=LeaveOneGroupOut())
    result = summarize(df["label"], pred)
    sr = df[df["label"] != "flat"]
    sr_pred = cross_val_predict(model, sr[features], sr["label"], groups=sr["group"], cv=LeaveOneGroupOut())
    sr_label = sr["label"].to_numpy()
    return pred, {**result, "sr_bal_acc": balanced_accuracy_score(sr_label, sr_pred),
                  "sr_r_step": float((sr_pred[sr_label == "dansa"] == "dansa").mean()),
                  "sr_r_rough": float((sr_pred[sr_label == "dekobo"] == "dekobo").mean())}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", default="configs/sessions/10.31.csv")
    parser.add_argument("--data-dir", default="wheelchair_data/10.31")
    parser.add_argument("--wheelchair", default="standard", choices=["standard", "original", "all"])
    parser.add_argument("--exclude", nargs="*", default=[], help="使わないセッション ID")
    parser.add_argument("--flat-blocks", type=int, default=1,
                        help="flat のセッションを時間で何個のグループに分けるか(10 月上旬は 5。1 ならセッション単位)")
    parser.add_argument("--tag", default="", help="出力のフォルダ名に付ける名前")
    parser.add_argument("--output-dir", default="data/analysis/20261031_button_lag")
    args = parser.parse_args()

    out = ROOT / args.output_dir / (args.wheelchair + (f"_{args.tag}" if args.tag else ""))
    out.mkdir(parents=True, exist_ok=True)
    meta = pd.read_csv(ROOT / args.sessions, dtype={"session_id": str})
    if args.wheelchair != "all":
        meta = meta[meta["wheelchair"] == args.wheelchair]
    meta = meta[~meta["session_id"].isin(args.exclude)]
    sessions = {s: load_session(ROOT / args.data_dir / s) for s in meta["session_id"]}
    kind_of = dict(zip(meta["session_id"], meta["kind"]))
    chair_of = dict(zip(meta["session_id"], meta["wheelchair"]))

    # 1. 揺れの閾値(flat セッションの包絡線)と、通過ごとのラグ
    flat_env = np.concatenate([sessions[s]["env"] for s, k in kind_of.items() if k == "flat"])
    threshold = float(np.percentile(flat_env, ACTIVE_PERCENTILE))
    passes = pd.concat(
        [add_activity(load_passes(ROOT / args.data_dir / s), sessions[s], threshold).assign(
            session=s, wheelchair=chair_of[s]) for s, k in kind_of.items() if k != "flat"],
        ignore_index=True,
    )
    passes.to_csv(out / "passes.csv", index=False)
    ok = passes[~passes["cancelled"]]
    print(f"揺れの閾値: {threshold:.2f} m/s²（flat の包絡線の {ACTIVE_PERCENTILE:g} パーセンタイル）")
    print(f"通過 {len(passes)}（取り消し {int(passes['cancelled'].sum())}、揺れなし {int(ok['onset_ms'].isna().sum())}）")
    pd.set_option("display.width", 200)
    print(ok.groupby(["sub"])[["dur_s", "lag_start_s", "lag_stop_s"]].median().round(2))
    print(ok.groupby(["sub", "wheelchair"])[["lag_start_s", "lag_stop_s"]].median().round(2))
    plot_lags(passes, out / "lag_hist.png")
    examples = [("20261031145759", 0, 30), ("20261031144423", 0, 30), ("20261031150809", 0, 30),
                ("20261031145017", 0, 25)]
    plot_examples([e for e in examples if e[0] in sessions], sessions, passes, threshold,
                  out / "waveform_examples.png")

    # 2. ラベルの区間を変えて評価
    conditions = ["pre0.5", "button", *[f"shift_{d:g}" for d in SHIFTS_S], "activity"]
    result_rows, count_rows, chair_rows = [], [], []
    for window_s in WINDOWS_S:
        feats = {s: window_features(sess, window_s) for s, sess in sessions.items()}
        for condition in conditions:
            frames = []
            for s, win in feats.items():
                p = passes[passes["session"] == s]
                intervals, dropped = intervals_for(p, condition) if len(p) else ({}, [])
                labels = label_windows(win, window_s, kind_of[s], intervals, dropped)
                win = win.assign(label=labels, group=s, wheelchair=chair_of[s]).dropna(subset=["label"])
                if kind_of[s] == "flat" and args.flat_blocks > 1:
                    win = split_blocks(win, args.flat_blocks, window_s)
                frames.append(win)
            df = pd.concat(frames, ignore_index=True)
            n = df["label"].value_counts()
            for (feature_set, features), (model_name, model) in itertools.product(
                    FEATURE_SETS.items(), models().items()):
                pred, res = evaluate(df, features, model)
                key = {"window_s": window_s, "condition": condition, "features": feature_set, "model": model_name}
                result_rows.append({**key, **{f"n_{DISPLAY[k]}": int(n.get(k, 0)) for k in LABELS}, **res})
                m = confusion_matrix(df["label"], pred, labels=LABELS)
                for i, t in enumerate(LABELS):
                    for j, q in enumerate(LABELS):
                        count_rows.append({**key, "true": DISPLAY[t], "pred": DISPLAY[q], "n": int(m[i, j])})
                d = df.assign(pred=pred)
                for (chair, t), sub in d.groupby(["wheelchair", "label"]):
                    chair_rows.append({**key, "wheelchair": chair, "true": DISPLAY[t], "n": len(sub),
                                       "recall": float((sub["pred"] == t).mean())})
                print(f"{window_s:.1f}s {condition:9s} {feature_set:5s} {model_name:12s} "
                      f"3クラス flat/step/rough={res['r_flat']:.2f}/{res['r_step']:.2f}/{res['r_rough']:.2f} "
                      f"2クラス step/rough={res['sr_r_step']:.2f}/{res['sr_r_rough']:.2f}", flush=True)

    pd.DataFrame(result_rows).to_csv(out / "results.csv", index=False)
    pd.DataFrame(count_rows).to_csv(out / "confusion_counts.csv", index=False)
    pd.DataFrame(chair_rows).to_csv(out / "recall_by_wheelchair.csv", index=False)


if __name__ == "__main__":
    main()
