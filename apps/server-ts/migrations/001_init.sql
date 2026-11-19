-- 走行(session)・判定結果(detection)・生データ(raw_file)。docs/knowledge/2026-11-18/20261118_local_server_plan.md の「設計の下書き」

CREATE TABLE sessions (
  id            uuid PRIMARY KEY,                 -- アプリが作る。再送しても同じ走行になる(冪等)
  device_id     text NOT NULL,
  started_at    timestamptz NOT NULL,
  app_version   text NOT NULL,
  model_version text NOT NULL,
  wheelchair    text,                             -- 今回は入力しない(空欄)
  weight_kg     real,                             -- 今回は入力しない(空欄)
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE detections (
  session_id      uuid   NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  window_start_ms bigint NOT NULL,                -- 窓の始まり(センサーのタイムスタンプ [ms]。研究のデータは epoch ミリ秒。アプリの実機・エミュレーターでの基準は ② で確かめる)
  window_s        real   NOT NULL,
  class           text   NOT NULL CHECK (class IN ('flat', 'step', 'rough')),
  scores          jsonb  NOT NULL,                -- SVM の決定関数の値(確率ではない)。{"flat":..,"step":..,"rough":..}
  lat             double precision,               -- GPS が取れなかった窓は NULL
  lon             double precision,
  accuracy_m      real,
  located_at_ms   bigint,                         -- 位置を取った時刻(窓の時刻とのずれを後で評価する)
  received_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (session_id, window_start_ms),      -- 同じバッチを再送しても二重にならない
  CHECK ((lat IS NULL) = (lon IS NULL)),
  CHECK (lat IS NULL OR (lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180))
);

CREATE INDEX detections_class_idx ON detections (class) WHERE lat IS NOT NULL;

CREATE TABLE raw_files (
  session_id   uuid PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
  object_key   text   NOT NULL,
  size_bytes   bigint NOT NULL,
  sha256       text   NOT NULL,                   -- アプリが送る。取り出して照合するのは検証用スクリプト
  uploaded_at  timestamptz NOT NULL DEFAULT now()
);
