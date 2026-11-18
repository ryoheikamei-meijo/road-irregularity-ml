-- window_start_ms は、アプリではセンサーのタイムスタンプ(端末の起動からの ms)で、epoch ではない。
-- 地図・走行の時刻には壁時計(epoch ms)が要るので、別の列にする。研究の記録(PC から送る分)は、センサーの時刻がそのまま epoch。
ALTER TABLE detections ADD COLUMN window_wall_ms bigint;
COMMENT ON COLUMN detections.window_start_ms IS '窓の始まり。センサーのタイムスタンプ[ms]。アプリでは端末の起動から、研究の記録では epoch。生データ(input.csv)の timestamp 列と同じ基準';
COMMENT ON COLUMN detections.window_wall_ms IS '窓の始まりの壁時計(epoch ms)。アプリでは、センサー時刻に「壁時計 − 起動からの時間」のずれを足して求める';
