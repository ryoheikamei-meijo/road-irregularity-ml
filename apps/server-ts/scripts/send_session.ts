/**
 * 記録済みの走行を、アプリの代わりに PC から API へ送り、保存されたことを確かめる(段階 ①)。
 *
 * 使い方(サーバーを `npm run dev` で起動してから。Kotlin 版(apps/server)に送るときは `./gradlew run` で起動し、`API_URL` を付けてもよい):
 *   npm run send -- <走行のフォルダ> <PC の判定の CSV> [--raw <生データのファイル>]
 *   例: npm run send -- ../../wheelchair_data/11.1/20261101142339 ../../data/analysis/20261116_export_onnx/parity/20261101142339.csv
 *
 * やること
 *   1. 走行を登録 → 判定結果を 10 秒分ずつのバッチで送る(位置は、gps.csv の窓の終わりに一番近い GPS。5 秒以上離れていたら付けない)
 *   2. 最初のバッチをもう一度送り、二重に保存されないこと(再送)を確かめる
 *   3. 署名付き URL で生データを S3 へ直接 PUT → 完了を通知
 *   4. 確認: DB の件数・クラスが元の CSV と一致するか、取り出した生データのハッシュが元と一致するか
 * wheelchair_data は読むだけで、書き換えない。
 */
import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { loadConfig } from "../src/config.js";
import { createPool } from "../src/db.js";
import { createStorage } from "../src/s3.js";

const MODEL_CLASS: Record<string, "flat" | "step" | "rough"> = { flat: "flat", dansa: "step", dekobo: "rough" };
const WINDOW_S = 2.0;
const BATCH_WINDOWS = 20; // 0.5 秒ごとの窓 × 20 = 10 秒分
const GPS_MAX_GAP_MS = 5000;

function readCsv(text: string): Record<string, string>[] {
  const [head, ...lines] = text.trim().split("\n");
  const cols = head!.split(",");
  return lines.map((l) => Object.fromEntries(l.split(",").map((v, i) => [cols[i]!, v])));
}

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const positional = process.argv.slice(2).filter((a, i, all) => !a.startsWith("--") && !(i > 0 && all[i - 1]!.startsWith("--")));
const [sessionDir, parityCsv] = positional;
if (!sessionDir || !parityCsv) {
  console.error("使い方: npm run send -- <走行のフォルダ> <PC の判定の CSV> [--raw <ファイル>]");
  process.exit(2);
}
const rawPath = arg("--raw") ?? `${sessionDir}/acc.csv`;
const base = process.env["API_URL"] ?? "http://127.0.0.1:8787";
const config = loadConfig();
const headers = { "x-api-key": config.API_KEY, "content-type": "application/json" };

async function call(path: string, body: unknown, ok: number[] = [200, 201]): Promise<Record<string, unknown>> {
  const r = await fetch(base + path, { method: "POST", headers, body: JSON.stringify(body) });
  const j = (await r.json()) as Record<string, unknown>;
  if (!ok.includes(r.status)) throw new Error(`${path} -> ${r.status} ${JSON.stringify(j)}`);
  return j;
}

const parity = readCsv(await readFile(parityCsv, "utf-8"));
const gps = readCsv(await readFile(`${sessionDir}/gps.csv`, "utf-8")).map((g) => ({
  t: Number(g["timestamp_ms"]), lat: Number(g["latitude"]), lon: Number(g["longitude"]), acc: Number(g["accuracy_m"]),
}));
const startedMs = Number(parity[0]!["start_ms"]);

const detections = parity.map((p) => {
  const start = Math.round(Number(p["start_ms"]));
  const end = start + WINDOW_S * 1000;
  let best: (typeof gps)[number] | undefined;
  for (const g of gps) if (!best || Math.abs(g.t - end) < Math.abs(best.t - end)) best = g;
  const near = best && Math.abs(best.t - end) <= GPS_MAX_GAP_MS ? best : undefined;
  return {
    window_start_ms: start, window_wall_ms: start, window_s: WINDOW_S, class: MODEL_CLASS[p["onnx_pred"]!]!,
    scores: { step: Number(p["onnx_score_dansa"]), rough: Number(p["onnx_score_dekobo"]), flat: Number(p["onnx_score_flat"]) },
    ...(near ? { lat: near.lat, lon: near.lon, accuracy_m: near.acc, located_at_ms: near.t } : {}),
  };
});

const sessionId = randomUUID();
console.log(`走行 ${sessionId}: 窓 ${detections.length} 件、位置つき ${detections.filter((d) => d.lat !== undefined).length} 件`);
await call("/sessions", {
  id: sessionId, device_id: "pc-replay", started_at: new Date(startedMs).toISOString(),
  app_version: "send_session.ts", model_version: "v4_20261118",
});

let inserted = 0;
const batches: (typeof detections)[] = [];
for (let i = 0; i < detections.length; i += BATCH_WINDOWS) batches.push(detections.slice(i, i + BATCH_WINDOWS));
for (const b of batches) inserted += (await call(`/sessions/${sessionId}/detections`, { detections: b }))["inserted"] as number;
const again = await call(`/sessions/${sessionId}/detections`, { detections: batches[0] });
console.log(`バッチ ${batches.length} 個を送信: 保存 ${inserted} 件。最初のバッチの再送 → 保存 ${again["inserted"]}、重複 ${again["duplicates"]}`);

const raw = await readFile(rawPath);
const sha256 = createHash("sha256").update(raw).digest("hex");
const { url, key } = (await call(`/sessions/${sessionId}/raw-upload-url`, {})) as { url: string; key: string };
const t0 = performance.now();
const put = await fetch(url, { method: "PUT", body: raw });
if (!put.ok) throw new Error(`PUT -> ${put.status} ${await put.text()}`);
await call(`/sessions/${sessionId}/raw-complete`, { size_bytes: raw.length, sha256 });
console.log(`生データ ${(raw.length / 1048576).toFixed(1)} MB を署名付き URL で PUT（${((performance.now() - t0) / 1000).toFixed(2)} 秒）`);

// 確認
const pool = createPool(config.DATABASE_URL);
const rows = (await pool.query<{ class: string; n: number; located: number }>(
  "SELECT class, count(*)::int AS n, count(lat)::int AS located FROM detections WHERE session_id = $1 GROUP BY class", [sessionId])).rows;
await pool.end();
const dbCount = Object.fromEntries(rows.map((r) => [r.class, r.n]));
const csvCount: Record<string, number> = {};
for (const d of detections) csvCount[d.class] = (csvCount[d.class] ?? 0) + 1;
const got = Buffer.from(await (await fetch(await createStorage(config).presignGet(key))).arrayBuffer());
const checks = {
  "件数とクラスが元の CSV と一致": JSON.stringify(Object.entries(dbCount).sort()) === JSON.stringify(Object.entries(csvCount).sort()),
  "再送で二重にならない": again["inserted"] === 0,
  "取り出した生データのハッシュが一致": createHash("sha256").update(got).digest("hex") === sha256,
};
console.log("DB のクラス別の件数:", dbCount);
for (const [k, v] of Object.entries(checks)) console.log(`${v ? "OK" : "NG"}  ${k}`);
if (!Object.values(checks).every(Boolean)) process.exit(1);
