# research-miura-app

## Androidのデータのパスについて

2026/0602/17:10ごとに検証した結果以下のパスにあることを確認した。

```bash
/storage/self/primary/Android/data/com.example.myapplication/files/csv/acc_2026-06-02.csv
```

### コーディングエージェントが端末のCSVを見る方法（adb）

端末を USB でつなぎ、USB デバッグを有効にしておけば、`adb` で端末の CSV を取り出して確認できる（2026/10/31 に確認）。

- `adb` は PATH に入っていないので、`~/Library/Android/sdk/platform-tools/adb` をフルパスで使う。
- 今の保存先は `files/csv/<セッションID>/`（下の「CSVの構成」）。
- 取り出したファイルは、リポジトリの外（エージェントの作業用フォルダなど）に置く。`data/` は `.gitignore` に入っているので、ここに置いてもコミットはされない。
- `adb pull` はコピーするだけで、端末のデータは変わらない。端末のファイルを消す・書き換える操作（`adb shell rm` など）は、利用者に確認してから行う。

```bash
ADB=~/Library/Android/sdk/platform-tools/adb
CSV_DIR=/storage/self/primary/Android/data/com.example.myapplication/files/csv

$ADB devices                                   # 端末がつながっているか（device と表示されればよい）
$ADB shell ls -t $CSV_DIR | head               # セッションの一覧（新しい順）
$ADB pull $CSV_DIR/<セッションID> <保存先>      # 1 セッション分のフォルダを取り出す
$ADB pull $CSV_DIR/sessions_index.csv <保存先>  # 全セッションの一覧を取り出す
```

## CSVの構成（2026/10 更新）

`files/csv/` の下に、セッションごとのフォルダ（`<セッションID>/`、`yyyyMMddHHmmss`）と、全セッションの一覧（`sessions_index.csv`）が保存される。

```
files/csv/
├── sessions_index.csv          全セッションの結果の一覧
└── <セッションID>/
    ├── acc.csv                 加速度と姿勢（解析の基本）
    ├── gyro.csv                角速度
    ├── linear_acc.csv          重力を除いた加速度（比較用）
    ├── dansa.csv               段差ボタンの記録（押したときだけ作られる）
    ├── dekobo.csv              凸凹ボタンの記録（押したときだけ作られる）
    ├── gps.csv                 GPS の位置（計測中、ボタンに関係なく 1 秒ごと）
    └── session_result.csv      そのセッションの結果
```

### 時刻の列について（共通）

| 列 | 単位 | 意味 | 使いどころ |
| --- | --- | --- | --- |
| `timestamp` / `timestamp_ms` | ms（Unix 時刻） | CSV に書き込んだときの端末の時計 | 日時の確認。センサーが測った時刻とは少しずれる |
| `elapsed` | ms | 計測開始（START）からの時間。センサーイベントの時刻から計算 | 1 つのファイルの中での時間軸 |
| `eventTimestampNs` | ns | センサーが値を測った時刻（`SensorEvent.timestamp`） | **`acc.csv`・`gyro.csv`・`linear_acc.csv` どうしの時刻合わせ**。3 つのファイルは別々のセンサーイベントで書かれるので、行どうしは対応していない |
| `elapsed_ms`（`dansa.csv`・`dekobo.csv`） | ms | 計測開始からの時間。グラフ描画の処理で 250ms ごとに更新される値 | ボタンを押した時刻。**250ms 程度の粗さ**があり、`acc.csv` の `elapsed` とは別の時計で数えている |
| `sensor_elapsed_ms`（`dansa.csv`・`dekobo.csv`） | ms | 計測開始からの時間。`acc.csv` の `elapsed` と同じ時計（センサーの時刻の基準）で、ボタンを押した瞬間に計算した値 | **ボタンの時刻と `acc.csv` を合わせるときはこちらを使う**（2026/10 末に追加） |

### `acc.csv`：加速度と姿勢（解析の基本）

加速度センサーのイベントごとに 1 行（要求 2ms、実測は約 3ms 間隔）。

| 列 | 単位 | 役割 |
| --- | --- | --- |
| `timestamp`, `elapsed` | ms | 時刻（上の表） |
| `accX`, `accY`, `accZ` | m/s² | 加速度（`TYPE_ACCELEROMETER`）。**重力を含む、端末の座標系**の生の値。解析では、姿勢を使って世界座標系に変換し、z から重力を引いている |
| `speedMps` | m/s | GPS の速度（取れないときは空）。GPS の更新は遅く、0 のことが多いので参考程度 |
| `rotX`, `rotY`, `rotZ`, `rotW` | なし | その時点の姿勢（`TYPE_ROTATION_VECTOR` のクォータニオン）。**世界座標系（X 東・Y 北・Z 上）への変換に使う**。地磁気を使うので、車椅子の鉄のフレームの影響を受ける可能性がある |
| `gameRotX`, `gameRotY`, `gameRotZ`, `gameRotW` | なし | その時点の姿勢（`TYPE_GAME_ROTATION_VECTOR`）。**地磁気を使わない**ので、鉄のフレームの影響を受けない。Z は上だが、Y は北を向かず、時間とともに少しずつずれる。`rot*` と比べて、z 軸の変換がどちらで安定するかを確かめるために記録している |
| `eventTimestampNs` | ns | センサーが測った時刻。`gyro.csv`・`linear_acc.csv` との時刻合わせに使う |

- `rot*`・`gameRot*` は、その行の時点で最後に届いた姿勢の値。姿勢は加速度と同じ周期で登録している（以前は `SENSOR_DELAY_NORMAL` で、約 5Hz でしか更新されていなかった）。
- `gameRot*`・`eventTimestampNs` は 2026/10 に末尾に追加した列。既存の列の並びは変えていないので、列名で読む解析コードはそのまま動く。

### `gyro.csv`：角速度

ジャイロのイベントごとに 1 行（加速度と同じ周期で登録）。

| 列 | 単位 | 役割 |
| --- | --- | --- |
| `timestamp`, `elapsed`, `eventTimestampNs` | ms / ms / ns | 時刻（上の表） |
| `gyroX`, `gyroY`, `gyroZ` | rad/s | 角速度（`TYPE_GYROSCOPE`、**端末の座標系**、反時計回りが正）。段差での車体の傾き（ピッチ）の変化を見るために記録している |

### `linear_acc.csv`：重力を除いた加速度（比較用）

| 列 | 単位 | 役割 |
| --- | --- | --- |
| `timestamp`, `elapsed`, `eventTimestampNs` | ms / ms / ns | 時刻（上の表） |
| `linAccX`, `linAccY`, `linAccZ` | m/s² | 重力を除いた加速度（`TYPE_LINEAR_ACCELERATION`、**端末の座標系**）。端末が加速度とジャイロから計算した値で、機種によって計算の仕方が違い、オフセットが残ることがある（公式ドキュメント）。解析は `acc.csv` を基本にし、こちらは今の重力の引き方と比べるために記録している |

### `gps.csv`：GPS の位置（1 秒ごと）

計測中、ボタンを押しているかどうかに関係なく、1 秒ごとに 1 行。flat のセッションなど、ボタンを押さないセッションでも、どこを走ったかを後から確かめるためのもの（2026/10/31 に追加）。

| 列 | 単位 | 役割 |
| --- | --- | --- |
| `timestamp_ms`, `sensor_elapsed_ms` | ms | 時刻（上の表。`sensor_elapsed_ms` は `acc.csv` の `elapsed` と同じ時計） |
| `latitude`, `longitude` | 度 | その時点で最後に取れた GPS の位置。まだ一度も取れていなければ空 |
| `accuracy_m` | m | 位置の精度（端末の推定。小さいほど正確） |
| `speed_mps` | m/s | GPS の速度 |
| `fix_age_ms` | ms | 最後に位置が更新されてからの時間。大きい（数秒以上）ときは、GPS が止まっていて古い位置のまま |

### `dansa.csv` / `dekobo.csv`：段差・凸凹ボタンの記録

ボタンを押したとき、および記録中の 1 秒ごとに 1 行。そのセッションで一度も押さなければ、ファイルは作られない。

| 列 | 単位 | 役割 |
| --- | --- | --- |
| `timestamp_ms`, `elapsed_ms` | ms | 時刻（上の表。`elapsed_ms` は 250ms 程度の粗さ） |
| `acc_x`, `acc_y`, `acc_z` | m/s² | その時点の加速度（端末の座標系の生の値）。確認用 |
| `latitude`, `longitude` | 度 | その時点の GPS の位置（取れないときは空） |
| `event` | ― | 何の記録か（下の表） |
| `sensor_elapsed_ms` | ms | 時刻（上の表。`acc.csv` の `elapsed` と同じ時計） |
| `pass_id` | ― | `dansa.csv` のみ。セッション内の段差の通過の番号（1, 2, 3…）。`dansa_start`・`dansa_during`・`dansa_stop`・`dansa_cancel` に入る |
| `direction` | ― | `dansa.csv` のみ。`up`（上り）か `down`（下り） |
| `pass_type` | ― | `dansa.csv` のみ。上りの `dansa_stop` の行に、`stop`（段差にぶつかって止まった）か `climb`（止まらずに乗り越えた）。下りは空 |

- `sensor_elapsed_ms` 以降の列は 2026/10 末に末尾に追加した。それより前の CSV には無い。

| `event` の値 | 意味 |
| --- | --- |
| `dansa_start` / `dansa_stop`（凸凹は `dekobo_*`） | 段差（凸凹）の 1 回の区間の始まりと終わり。段差は「段差↑ START」「段差↓ START」で始め、上りは「STOP: 止まった」「STOP: 乗り越えた」、下りは「STOP: 下り」で終える |
| `dansa_during` | 区間の記録中に 1 秒ごとに残す位置 |
| `dansa_cancel` | 「段差 取消」ボタン。記録中、または直前に終えた通過（同じ `pass_id`）を無効にする。解析では、この `pass_id` の通過を除く。通過の途中で計測を終了したときも、自動で記録する |
| `dansa_cont_start` / `dansa_cont_stop` | （廃止）継続ボタン。行ったり来たりする区間など、段差（凸凹）が続く区間の始まりと終わり。計測を終了したときに区間が続いていれば、`_stop` を自動で記録する。2026/10 末までの CSV にだけある |
| `dansa_cont_during` | （廃止）継続の区間の記録中に 1 秒ごとに残す位置 |

- 解析（方針A）では、継続の区間（`_cont_start` 〜 `_cont_stop`）を段差・凸凹のラベルにしている。
- 2026/10 末に継続ボタンを廃止した。継続の区間には、折り返しや通過のあいだの静かな時間（実際は flat）が入り、段差と凸凹の取り違えの原因になっていたため。今後は、段差・凸凹を**実際に通過しているあいだだけ** START〜STOP を押す。

### `session_result.csv` / `sessions_index.csv`：セッションの結果

`session_result.csv` はそのセッションの 1 行だけ、`sessions_index.csv` は全セッションの行を追記していく一覧。列は同じ。

| 列 | 役割 |
| --- | --- |
| `session_id` | セッション ID（フォルダ名と同じ） |
| `result` | `success`（STOP で終了）か `failed`（失敗として終了） |
| `reason` | 失敗の理由。`button_miss`（MISS ボタン）、`cleared`（CLEAR ボタン）。成功なら空 |
| `started_at_ms`, `ended_at_ms`, `duration_ms` | 開始・終了の時刻（Unix 時刻、ms）と長さ |
| `weight_kg` | 車椅子に乗った人の体重（設定した値。未設定なら空） |
| `dansa_cont`, `dekobo_cont` | そのセッションで段差・凸凹の継続ボタンを 1 回でも押したか（`true` / `false`）。継続ボタンを廃止したので、2026/10 末以降のセッションは常に `false`。過去のセッションと列をそろえるために残している |
| `wheelchair` | 使った車椅子。`original`（元々使っていた車椅子）か `standard`（新しく買った汎用の車椅子）。「車椅子設定」で選んだ、計測開始時の値。未設定なら空。2026/10 末に追加した列で、それより前のセッションは空 |
| `session_kind` | そのセッションで測るもの。`flat` / `step`（段差）/ `rough`（凸凹）。「種類設定」で選んだ、計測開始時の値。未設定なら空。ボタンの記録が無いセッションが、flat なのか押し忘れなのかを区別するためのもの |
| `memo` | 自由記述のメモ（場所・路面など）。START を押した時点の入力欄の内容。改行は空白にする |

- `session_kind`・`memo` は 2026/10/31 に追加した列で、それより前のセッションは空。種類と車椅子は次のセッションにも引き継がれ、メモの入力欄も消えないので、セッションごとに START の前に確認する。

