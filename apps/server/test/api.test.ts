import { createHash, randomBytes } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { detection, newSession, setup } from "./helpers.js";

type Env = Awaited<ReturnType<typeof setup>>;
let t: Env;
beforeAll(async () => { t = await setup(); });
afterAll(async () => { await t.teardown(); });

const json = async (r: Response) => (await r.json()) as Record<string, unknown>;

describe("認証", () => {
  it("/health は鍵が無くても通る", async () => {
    const r = await t.app.request("/health");
    expect(r.status).toBe(200);
  });
  it("鍵が無い・違うときは 401", async () => {
    const body = newSession();
    expect((await t.post("/sessions", body, { "content-type": "application/json" })).status).toBe(401);
    expect((await t.post("/sessions", body, { "content-type": "application/json", "x-api-key": "wrong-key-xx" })).status).toBe(401);
  });
});

describe("走行の登録", () => {
  it("作成は 201、同じ id の再送は 200（冪等）", async () => {
    const s = newSession();
    const a = await t.post("/sessions", s);
    expect(a.status).toBe(201);
    expect(await json(a)).toMatchObject({ created: true });
    const b = await t.post("/sessions", s);
    expect(b.status).toBe(200);
    expect(await json(b)).toMatchObject({ created: false });
    expect((await t.pool.query("SELECT count(*)::int AS n FROM sessions WHERE id = $1", [s.id])).rows[0].n).toBe(1);
  });
  it("同じ id で別の端末なら 409", async () => {
    const s = newSession();
    await t.post("/sessions", s);
    expect((await t.post("/sessions", { ...s, device_id: "other" })).status).toBe(409);
  });
  it("不正な入力は 400 で、理由が返る", async () => {
    const r = await t.post("/sessions", { ...newSession(), id: "not-a-uuid", started_at: "yesterday" });
    expect(r.status).toBe(400);
    const j = (await json(r)) as { issues: { path: string }[] };
    expect(j.issues.map((i) => i.path).sort()).toEqual(["id", "started_at"]);
    expect((await t.post("/sessions", "{broken")).status).toBe(400);
  });
});

describe("判定結果のバッチ", () => {
  it("保存でき、同じバッチを再送しても二重にならない", async () => {
    const s = newSession(); await t.post("/sessions", s);
    const batch = { detections: [detection(1000), detection(1500, { class: "step" }), detection(2000, { class: "rough" })] };
    const a = await t.post(`/sessions/${s.id}/detections`, batch);
    expect(await json(a)).toEqual({ received: 3, inserted: 3, duplicates: 0 });
    const b = await t.post(`/sessions/${s.id}/detections`, batch);
    expect(await json(b)).toEqual({ received: 3, inserted: 0, duplicates: 3 });
    const rows = (await t.pool.query("SELECT class, scores FROM detections WHERE session_id = $1 ORDER BY window_start_ms", [s.id])).rows;
    expect(rows.map((r) => r.class)).toEqual(["flat", "step", "rough"]);
    expect(rows[0].scores).toEqual({ flat: 1.2, step: -0.4, rough: -0.9 });
  });
  it("壁時計(window_wall_ms)は、あれば保存され、無ければ NULL", async () => {
    const s = newSession(); await t.post("/sessions", s);
    await t.post(`/sessions/${s.id}/detections`, { detections: [detection(1000, { window_wall_ms: 1793510619944 }), detection(1500)] });
    const rows = (await t.pool.query("SELECT window_start_ms::int AS s, window_wall_ms::bigint::text AS w FROM detections WHERE session_id = $1 ORDER BY 1", [s.id])).rows;
    expect(rows).toEqual([{ s: 1000, w: "1793510619944" }, { s: 1500, w: null }]);
  });
  it("新しい窓と再送の窓が混ざっても、新しい分だけ入る", async () => {
    const s = newSession(); await t.post("/sessions", s);
    await t.post(`/sessions/${s.id}/detections`, { detections: [detection(1000), detection(1500)] });
    const r = await t.post(`/sessions/${s.id}/detections`, { detections: [detection(1500), detection(2000), detection(2500)] });
    expect(await json(r)).toEqual({ received: 3, inserted: 2, duplicates: 1 });
  });
  it("1 つのバッチの中に同じ窓があっても、1 件だけ入る", async () => {
    const s = newSession(); await t.post("/sessions", s);
    const r = await t.post(`/sessions/${s.id}/detections`, { detections: [detection(1000), detection(1000)] });
    expect(await json(r)).toEqual({ received: 2, inserted: 1, duplicates: 1 });
  });
  it("位置が取れなかった窓は NULL で保存される", async () => {
    const s = newSession(); await t.post("/sessions", s);
    const d = detection(1000); delete (d as Record<string, unknown>)["lat"]; delete (d as Record<string, unknown>)["lon"];
    delete (d as Record<string, unknown>)["accuracy_m"]; delete (d as Record<string, unknown>)["located_at_ms"];
    expect((await t.post(`/sessions/${s.id}/detections`, { detections: [d] })).status).toBe(200);
    const row = (await t.pool.query("SELECT lat, lon, accuracy_m FROM detections WHERE session_id = $1", [s.id])).rows[0];
    expect(row).toEqual({ lat: null, lon: null, accuracy_m: null });
  });
  it("lat だけ、範囲外、不明なクラス、空のバッチは 400", async () => {
    const s = newSession(); await t.post("/sessions", s);
    const bad = (d: unknown) => t.post(`/sessions/${s.id}/detections`, { detections: d });
    const noLon = detection(1000); delete (noLon as Record<string, unknown>)["lon"];
    expect((await bad([noLon])).status).toBe(400);
    expect((await bad([detection(1000, { lat: 91 })])).status).toBe(400);
    expect((await bad([detection(1000, { class: "bump" })])).status).toBe(400);
    expect((await bad([])).status).toBe(400);
  });
  it("登録の無い走行は 404、uuid でなければ 400", async () => {
    expect((await t.post(`/sessions/${newSession().id}/detections`, { detections: [detection(1)] })).status).toBe(404);
    expect((await t.post("/sessions/abc/detections", { detections: [detection(1)] })).status).toBe(400);
  });
});

describe("生データ（署名付き URL）", () => {
  it("URL を受け取り、ストレージへ直接 PUT し、完了を通知すると記録される。取り出すと同じ内容", async () => {
    const s = newSession(); await t.post("/sessions", s);
    const r = await t.post(`/sessions/${s.id}/raw-upload-url`, {});
    expect(r.status).toBe(200);
    const { url, key } = (await json(r)) as { url: string; key: string };
    expect(key).toBe(`sessions/${s.id}/input.csv`);
    const body = randomBytes(20 * 1024 * 1024); // Lambda の 6 MB を超える大きさ
    const sha256 = createHash("sha256").update(body).digest("hex");
    const put = await fetch(url, { method: "PUT", body });
    expect(put.status).toBe(200);
    const done = await t.post(`/sessions/${s.id}/raw-complete`, { size_bytes: body.length, sha256 });
    expect(await json(done)).toEqual({ key, size_bytes: body.length });
    const rec = (await t.pool.query("SELECT size_bytes::int AS size_bytes, sha256 FROM raw_files WHERE session_id = $1", [s.id])).rows[0];
    expect(rec).toEqual({ size_bytes: body.length, sha256 });
    const got = Buffer.from(await (await fetch(await t.storage.presignGet(key))).arrayBuffer());
    expect(createHash("sha256").update(got).digest("hex")).toBe(sha256);
    await t.storage.remove(key);
  });
  it("置かれていない・大きさが違うときの完了通知は 409", async () => {
    const s = newSession(); await t.post("/sessions", s);
    const sha256 = "a".repeat(64);
    expect((await t.post(`/sessions/${s.id}/raw-complete`, { size_bytes: 10, sha256 })).status).toBe(409);
    const { url, key } = (await json(await t.post(`/sessions/${s.id}/raw-upload-url`, {}))) as { url: string; key: string };
    await fetch(url, { method: "PUT", body: Buffer.from("0123456789") });
    const r = await t.post(`/sessions/${s.id}/raw-complete`, { size_bytes: 11, sha256 });
    expect(r.status).toBe(409);
    expect(await json(r)).toMatchObject({ error: "size_mismatch", stored: 10, declared: 11 });
    await t.storage.remove(key);
  });
  it("sha256 の形が違うと 400、登録の無い走行は 404", async () => {
    const s = newSession(); await t.post("/sessions", s);
    expect((await t.post(`/sessions/${s.id}/raw-complete`, { size_bytes: 1, sha256: "XYZ" })).status).toBe(400);
    expect((await t.post(`/sessions/${newSession().id}/raw-upload-url`, {})).status).toBe(404);
  });
});
