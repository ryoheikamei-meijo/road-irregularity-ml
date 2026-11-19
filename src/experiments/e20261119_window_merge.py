"""窓ごとの判定を、地図に出すために「まとめる」とき、どれくらいまとめるのが適切かを、これまでの計測で調べる。

背景
  判定は 2.0 秒の窓を 0.5 秒ずつずらして出すので、1 つの段差の衝撃が最大 4 つの窓に入り、地図に印が並ぶ。
  続いた窓を 1 つの「イベント」にまとめ、イベントごとに印を 1 つ出したい(docs/knowledge/2026-11-19/20261119_window_merge_design.md)。

まとめ方(クラスごとに独立。段差 dansa と凸凹 dekobo)
  1. gap : その クラスの窓の間に、他のクラスの窓が gap 個以下しか挟まらなければ、つなげて 1 つにする
  2. min_n : つないだあと、元の窓が min_n 個に満たないものは捨てる(単発の誤検知を消す)
  3. 代表 : イベントの中で、そのクラスの決定関数の値が最大の窓を、印の位置にする

評価(実際の判定と同じ、見ていない走行での判定を使う)
  - 判定は、leave-one-session-out(その走行を除いた 15 走行で学習した SVM。特徴量 core、傾きの基準 startmean10 = アプリの v4)。
    学習済みのモデルで全走行を判定すると、学習に使った走行を判定することになり、甘くなるため。
  - 段差: 通過(パス)ごとに、衝撃の時刻(区間の中で |z| が最大の時刻 peak_ms)を含むイベントがあれば検出。含む = 窓の範囲が peak_ms の ±1 秒に重なる
  - 凸凹: 通過ごとに、ラベルの区間(START + 1 秒〜STOP)に重なるイベントがあれば検出
  - 誤検知 : どの通過にも対応しないイベント。取り消した・除外した通過(excluded_passes.csv)に重なるものは数えない
  - 1 つの通過あたりのイベント数 : 1 に近いほど、印が重複していない
  - 位置のずれ : 段差の印(最大の窓の中心)と peak_ms の差。GPS の速度を掛けるとメートルになる

使い方: uv run python -m src.experiments.e20261119_window_merge
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.experiments.e20261031_button_lag import load_passes
from src.experiments.e20261031_button_lag import load_session
from src.experiments.e20261116_tilt_reference import excluded_passes
from src.experiments.e20261116_tilt_reference import labeled_windows
from src.experiments.e20261116_tilt_reference import passes_with_peak
from src.experiments.e20261116_tilt_reference import session_list
from src.roadml.core_model import CORE
from src.roadml.core_model import WINDOW_S
from src.roadml.evaluation import models

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/analysis/20261119_window_merge"
TILT_REF = "startmean10"
STRIDE_MS = 500.0
WIN_MS = WINDOW_S * 1000.0
PEAK_PAD_MS = 1000.0
GAPS = [0, 1, 2, 3, 4]
MIN_NS = [1, 2, 3, 4]
CLASSES = ["dansa", "dekobo"]


def loso_predictions(windows: pd.DataFrame) -> pd.DataFrame:
    """走行ごとに、その走行を除いて学習し、その走行の全部の窓(ラベルの無い窓も)を判定する。"""
    out = []
    for s in windows["session"].unique():
        train = windows[(windows["session"] != s)].dropna(subset=["label"])
        model = models()["SVM"].fit(train[CORE].to_numpy(), train["label"].to_numpy())
        test = windows[windows["session"] == s].copy()
        x = test[CORE].to_numpy()
        test["pred"] = model.predict(x)
        score = model.decision_function(x)
        for i, c in enumerate(model.classes_):
            test[f"score_{c}"] = score[:, i]
        out.append(test)
    return pd.concat(out, ignore_index=True)


def ground_truth(meta: pd.DataFrame) -> dict[str, dict]:
    """走行ごとの正解: 段差の衝撃の時刻、凸凹の区間、除く区間、走行の長さ(分)は後で窓から求める。"""
    ex = excluded_passes()
    gt = {}
    for s, d, k in zip(meta["session_id"], meta["day"], meta["kind"]):
        run_dir = ROOT / "wheelchair_data" / d / s
        steps, roughs, dropped = [], [], []
        if k != "flat":
            p = passes_with_peak(run_dir, load_session(run_dir))
            for kind, pid in zip(ex.loc[ex["session_id"] == s, "kind"], ex.loc[ex["session_id"] == s, "pass_id"]):
                p.loc[(p["kind"] == kind) & (p["pass_id"] == pid), "cancelled"] = True
            for r in p.itertuples():
                if r.cancelled:
                    dropped.append((r.start_ms, r.stop_ms))
                elif r.kind == "dansa":
                    steps.append(float(r.peak_ms))
                else:
                    roughs.append((r.start_ms + 1000.0, r.stop_ms))
        gt[s] = {"kind": k, "steps": steps, "roughs": roughs, "dropped": dropped}
    return gt


def speed_mps(meta: pd.DataFrame) -> float:
    """走っている間(0.3 m/s 以上)の GPS の速度の中央値(GPS のある走行だけ)。位置のずれを秒からメートルにするため。"""
    v = []
    for d, s in zip(meta["day"], meta["session_id"]):
        path = ROOT / "wheelchair_data" / d / s / "gps.csv"
        if not path.exists():  # 10/31 の走行には GPS が無い
            continue
        g = pd.read_csv(path)
        x = g["speed_mps"].to_numpy(float)
        v.append(x[np.isfinite(x) & (x >= 0.3)])
    return float(np.median(np.concatenate(v)))


def merge_events(sub: pd.DataFrame, cls: str, gap: int, min_n: int, min_score: float = -np.inf) -> list[dict]:
    """1 つの走行の窓から、クラス cls のイベント(窓の範囲と、決定関数の値が最大の窓)を作る。"""
    start0 = sub["start_ms"].iloc[0]
    idx = np.rint((sub["start_ms"].to_numpy() - start0) / STRIDE_MS).astype(int)  # 窓が抜けた所は、判定なしとして扱う
    n = idx.max() + 1
    pos = np.zeros(n, bool)
    score = np.full(n, -np.inf)
    pos[idx] = (sub["pred"].to_numpy() == cls)
    score[idx] = sub[f"score_{cls}"].to_numpy()
    filled = pos.copy()
    on = np.flatnonzero(pos)
    for a, b in zip(on[:-1], on[1:]):  # 間が gap 個以下なら、つなぐ
        if 1 < b - a <= gap + 1:
            filled[a:b] = True
    events = []
    i = 0
    while i < n:
        if not filled[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and filled[j + 1]:
            j += 1
        k = int(pos[i:j + 1].sum())
        peak = i + int(np.argmax(score[i:j + 1]))
        if k >= min_n and score[peak] >= min_score:
            events.append({"first": start0 + i * STRIDE_MS, "last_end": start0 + j * STRIDE_MS + WIN_MS,
                           "peak_center": start0 + peak * STRIDE_MS + WIN_MS / 2,  # 決定関数の値が最大の窓の中心
                           "first_center": start0 + i * STRIDE_MS + WIN_MS / 2,  # 最初の窓の中心
                           "mid_center": (start0 + i * STRIDE_MS + start0 + j * STRIDE_MS + WIN_MS) / 2,  # 範囲の真ん中
                           "n_pos": k})
        i = j + 1
    return events


def overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    return min(a1, b1) > max(a0, b0)


def evaluate(pred: pd.DataFrame, gt: dict, gap: int, min_n: int, mps: float, min_score: float = -np.inf, zpin: dict | None = None) -> dict:
    n_step = hit_step = n_rough = hit_rough = 0
    ev_per_step: list[int] = []
    ev_per_rough: list[int] = []
    false_step = false_rough = 0
    total_ev = {"dansa": 0, "dekobo": 0}
    dt: dict[str, list[float]] = {"peak_center": [], "first_center": [], "mid_center": [], "z_center": []}
    multi_step = multi_rough = 0
    false_flat = 0
    flat_minutes = 0.0
    minutes = 0.0
    for s, sub in pred.groupby("session"):
        sub = sub.sort_values("start_ms")
        g = gt[s]
        dur = (sub["start_ms"].iloc[-1] + WIN_MS - sub["start_ms"].iloc[0]) / 60000.0
        minutes += dur
        if g["kind"] == "flat":
            flat_minutes += dur
        n_step += len(g["steps"])
        n_rough += len(g["roughs"])
        for cls in CLASSES:
            events = merge_events(sub, cls, gap, min_n, min_score)
            if zpin is not None:  # 印の位置を、イベントの範囲で |z| が最大の時刻にする
                ts, az = zpin[s]
                for e in events:
                    m = (ts >= e["first"]) & (ts <= e["last_end"])
                    e["z_center"] = float(ts[m][np.argmax(az[m])]) if m.any() else e["peak_center"]
            total_ev[cls] += len(events)
            claimed = [0] * len(events)
            if cls == "dansa":
                for peak in g["steps"]:
                    hits = [i for i, e in enumerate(events) if overlaps(e["first"], e["last_end"], peak - PEAK_PAD_MS, peak + PEAK_PAD_MS)]
                    for i in hits:
                        claimed[i] += 1
                    if hits:
                        hit_step += 1
                        ev_per_step.append(len(hits))
                        best = min(hits, key=lambda i: abs(events[i]["peak_center"] - peak))
                        for key in dt:
                            if key in events[best]:
                                dt[key].append(abs(events[best][key] - peak) / 1000.0)
            else:
                for a, b in g["roughs"]:
                    hits = [i for i, e in enumerate(events) if overlaps(e["first"], e["last_end"], a, b)]
                    for i in hits:
                        claimed[i] += 1
                    if hits:
                        hit_rough += 1
                        ev_per_rough.append(len(hits))
            multi = sum(1 for c in claimed if c >= 2)  # 2 つ以上の通過をまとめてしまったイベント
            if cls == "dansa":
                multi_step += multi
            else:
                multi_rough += multi
            for i, e in enumerate(events):
                if claimed[i] == 0 and g["kind"] == "flat":
                    false_flat += 1
                if claimed[i] == 0 and not any(overlaps(e["first"], e["last_end"], a, b) for a, b in g["dropped"]):
                    if cls == "dansa":
                        false_step += 1
                    else:
                        false_rough += 1
    return {
        "gap": gap, "min_n": min_n, "min_score": min_score,
        "step_recall": hit_step / n_step, "step_ev_per_pass": float(np.mean(ev_per_step)) if ev_per_step else np.nan,
        "step_false_per_min": false_step / minutes, "step_events": total_ev["dansa"],
        "step_multi_events": multi_step, "rough_multi_events": multi_rough,
        "false_in_flat_per_min": false_flat / flat_minutes, "flat_minutes": flat_minutes,
        "step_dt_median_s": float(np.median(dt["peak_center"])), "step_dt_p90_s": float(np.percentile(dt["peak_center"], 90)),
        "dt_first_median_s": float(np.median(dt["first_center"])), "dt_first_p90_s": float(np.percentile(dt["first_center"], 90)),
        "dt_mid_median_s": float(np.median(dt["mid_center"])), "dt_mid_p90_s": float(np.percentile(dt["mid_center"], 90)),
        "step_dt_median_m": float(np.median(dt["peak_center"])) * mps,
        "dt_z_median_s": float(np.median(dt["z_center"])) if dt["z_center"] else np.nan, "dt_z_p90_s": float(np.percentile(dt["z_center"], 90)) if dt["z_center"] else np.nan,
        "rough_recall": hit_rough / n_rough, "rough_ev_per_pass": float(np.mean(ev_per_rough)) if ev_per_rough else np.nan,
        "rough_false_per_min": false_rough / minutes, "rough_events": total_ev["dekobo"],
        "n_step": n_step, "n_rough": n_rough, "minutes": minutes,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    meta = session_list()
    windows = labeled_windows(meta, TILT_REF)
    pred = loso_predictions(windows)
    pred.to_csv(OUT / "loso_predictions.csv", index=False)
    gt = ground_truth(meta)
    mps = speed_mps(meta)
    print(f"走行 {meta.shape[0]} 本、窓 {len(pred)}、走っている間の速度の中央値 {mps:.2f} m/s")
    lab = pred.dropna(subset=["label"])
    print("ラベルのある窓での判定(LOSO)の一致率:", f"{(lab['label'] == lab['pred']).mean():.3f}")
    print("全部の窓での判定の内訳:", pred["pred"].value_counts().to_dict())
    rows = [evaluate(pred, gt, g, m, mps) for g in GAPS for m in MIN_NS]
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "merge_grid.csv", index=False)
    r0 = res[(res["gap"] == 0) & (res["min_n"] == 1)].iloc[0]
    print(f"\n正解: 段差の通過 {int(r0['n_step'])}、凸凹の通過 {int(r0['n_rough'])}、走行の合計 {r0['minutes']:.1f} 分")
    print(f"まとめない(窓ごと): 段差の印 {int(r0['step_events'])}、凸凹の印 {int(r0['rough_events'])}  ※ gap=0・min_n=1 は、続いた窓だけをまとめた形")
    pd.set_option("display.width", 220)
    print(f"flat の走行は合計 {r0['flat_minutes']:.1f} 分")
    print("\n--- 段差 ---")
    print(res[["gap", "min_n", "step_recall", "step_ev_per_pass", "step_multi_events", "step_false_per_min", "step_events"]].round(3).to_string(index=False))
    print("\n--- 段差の印の位置のずれ(秒。peak_ms との差)。代表の取り方 3 通り ---")
    print(res[res["min_n"] == 3][["gap", "step_dt_median_s", "step_dt_p90_s", "dt_first_median_s", "dt_first_p90_s", "dt_mid_median_s", "dt_mid_p90_s"]].round(2).to_string(index=False))
    print("\n--- 凸凹 ---")
    print(res[["gap", "min_n", "rough_recall", "rough_ev_per_pass", "rough_multi_events", "rough_false_per_min", "rough_events"]].round(3).to_string(index=False))
    print("\n--- flat の走行だけでの誤検知(1 分あたり。段差・凸凹の合計) ---")
    print(res[["gap", "min_n", "false_in_flat_per_min"]].pivot(index="gap", columns="min_n", values="false_in_flat_per_min").round(2).to_string())
    spacing = []
    for s_, g_ in gt.items():
        p_ = sorted(g_["steps"])
        spacing += list(np.diff(p_) / 1000.0)
    print("\n段差の通過の間隔(秒。同じ走行の隣り合う通過)の分位点 0/5/25/50:", np.round(np.percentile(spacing, [0, 5, 25, 50]), 1))
    # 追加 1: イベントの強さ(決定関数の最大値)の下限
    print("\n--- gap=0 で、イベントの強さの下限を足したとき(min_n=2・3) ---")
    rows2 = [evaluate(pred, gt, 0, m, mps, t) for m in (2, 3) for t in (-np.inf, 0.0, 0.5, 1.0, 1.5)]
    r2 = pd.DataFrame(rows2)
    r2.to_csv(OUT / "merge_min_score.csv", index=False)
    print(r2[["min_n", "min_score", "step_recall", "step_ev_per_pass", "step_false_per_min", "step_events", "rough_recall", "rough_ev_per_pass", "rough_false_per_min", "rough_events", "false_in_flat_per_min"]].round(3).to_string(index=False))
    # 追加 2: 印の位置を |z| が最大の時刻にする
    from src.roadml.core_model import load_raw, signals
    zpin = {}
    for s_, d_ in zip(meta["session_id"], meta["day"]):
        sig = signals(load_raw(ROOT / "wheelchair_data" / d_ / s_), "window")
        zpin[s_] = (sig["ts"], np.abs(sig["z"]))
    rows3 = [evaluate(pred, gt, g_, 3, mps, -np.inf, zpin) for g_ in (0, 1, 2)]
    r3 = pd.DataFrame(rows3)
    print("\n--- 段差の印の位置のずれ(秒。min_n=3)。代表の取り方: 決定関数が最大の窓 / |z| が最大の時刻 ---")
    print(r3[["gap", "step_dt_median_s", "step_dt_p90_s", "dt_z_median_s", "dt_z_p90_s"]].round(2).to_string(index=False))
    raw = pred["pred"].value_counts()
    print(f"\n窓ごとの印の数(まとめない): 段差 {raw.get('dansa', 0)}、凸凹 {raw.get('dekobo', 0)}")


if __name__ == "__main__":
    main()
