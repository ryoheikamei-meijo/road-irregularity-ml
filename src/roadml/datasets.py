"""解析に使うセッションの一覧(configs/datasets/<名前>.yaml)。

スクリプトでは add_run_dir_args で --dataset(既定: rear_only_103_104)と --data-dir を受け取り、
resolve_run_dirs でセッションのフォルダの一覧にする。--data-dir を渡したときは、そのフォルダの
下の acc.csv のあるフォルダを全部使う(以前の /tmp/rear_only のような使い方)。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = "rear_only_103_104"


def load_dataset(name: str, root: Path = ROOT) -> list[Path]:
    path = root / "configs" / "datasets" / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(path)
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    run_dirs = [root / s for s in config["sessions"]]
    missing = [str(d) for d in run_dirs if not (d / "acc.csv").exists()]
    if missing:
        raise FileNotFoundError(f"acc.csv が無いセッション: {missing}")
    # 以前の /tmp/rear_only と同じく、セッション名(フォルダ名)の順に並べる
    return sorted(run_dirs, key=lambda d: d.name)


def add_run_dir_args(parser: argparse.ArgumentParser, default: str = DEFAULT_DATASET) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dataset", default=default,
                       help=f"configs/datasets/ のデータセット名(既定: {default})")
    group.add_argument("--data-dir", help="セッションのフォルダを並べたディレクトリ(--dataset の代わり)")


def resolve_run_dirs(args: argparse.Namespace) -> list[Path]:
    if getattr(args, "data_dir", None):
        return sorted(p for p in Path(args.data_dir).iterdir() if (p / "acc.csv").exists())
    return load_dataset(args.dataset)
