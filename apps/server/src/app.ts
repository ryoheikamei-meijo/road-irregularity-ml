import { timingSafeEqual } from "node:crypto";
import { Hono } from "hono";
import type { Context } from "hono";
import type pg from "pg";
import type { ZodType } from "zod";
import type { Config } from "./config.js";
import { detectionsBody, rawCompleteBody, sessionBody, sessionIdParam } from "./schemas.js";
import type { Storage } from "./s3.js";

export interface Deps {
  config: Config;
  pool: pg.Pool;
  storage: Storage;
}

const rawKey = (sessionId: string) => `sessions/${sessionId}/input.csv`;

function safeEqual(a: string, b: string): boolean {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

async function parseBody<T>(c: Context, schema: ZodType<T>): Promise<{ ok: true; data: T } | { ok: false; res: Response }> {
  let json: unknown;
  try {
    json = await c.req.json();
  } catch {
    return { ok: false, res: c.json({ error: "invalid_json" }, 400) };
  }
  const r = schema.safeParse(json);
  if (!r.success) {
    return { ok: false, res: c.json({ error: "validation", issues: r.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })) }, 400) };
  }
  return { ok: true, data: r.data };
}

export function createApp({ config, pool, storage }: Deps): Hono {
  const app = new Hono();

  app.onError((err, c) => {
    console.error("unhandled", err);
    return c.json({ error: "internal" }, 500);
  });

  app.get("/health", async (c) => {
    await pool.query("SELECT 1");
    return c.json({ ok: true });
  });

  // 共有キー。研究室内だけの前提で、強い認証ではない(アプリに埋め込むため)
  app.use("*", async (c, next) => {
    if (c.req.path === "/health") return next();
    const key = c.req.header("x-api-key");
    if (!key || !safeEqual(key, config.API_KEY)) return c.json({ error: "unauthorized" }, 401);
    return next();
  });

  /** 走行の登録。同じ id で再送しても同じ結果(冪等) */
  app.post("/sessions", async (c) => {
    const b = await parseBody(c, sessionBody);
    if (!b.ok) return b.res;
    const s = b.data;
    const ins = await pool.query(
      `INSERT INTO sessions (id, device_id, started_at, app_version, model_version, wheelchair, weight_kg)
       VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (id) DO NOTHING`,
      [s.id, s.device_id, s.started_at, s.app_version, s.model_version, s.wheelchair ?? null, s.weight_kg ?? null],
    );
    if (ins.rowCount === 1) return c.json({ id: s.id, created: true }, 201);
    const existing = await pool.query<{ device_id: string }>("SELECT device_id FROM sessions WHERE id = $1", [s.id]);
    if (existing.rows[0]?.device_id !== s.device_id) return c.json({ error: "session_id_conflict" }, 409);
    return c.json({ id: s.id, created: false }, 200);
  });

  /** 判定結果のバッチ。(session_id, window_start_ms) で重複を弾くので、再送しても二重にならない */
  app.post("/sessions/:id/detections", async (c) => {
    const id = sessionIdParam.safeParse(c.req.param("id"));
    if (!id.success) return c.json({ error: "invalid_session_id" }, 400);
    const b = await parseBody(c, detectionsBody);
    if (!b.ok) return b.res;
    const exists = await pool.query("SELECT 1 FROM sessions WHERE id = $1", [id.data]);
    if (exists.rowCount === 0) return c.json({ error: "session_not_found" }, 404);
    const rows = b.data.detections.map((d) => ({
      window_start_ms: d.window_start_ms, window_wall_ms: d.window_wall_ms ?? null, window_s: d.window_s, class: d.class, scores: d.scores,
      lat: d.lat ?? null, lon: d.lon ?? null, accuracy_m: d.accuracy_m ?? null, located_at_ms: d.located_at_ms ?? null,
    }));
    const ins = await pool.query(
      `INSERT INTO detections (session_id, window_start_ms, window_wall_ms, window_s, class, scores, lat, lon, accuracy_m, located_at_ms)
       SELECT $1::uuid, r.window_start_ms, r.window_wall_ms, r.window_s, r.class, r.scores, r.lat, r.lon, r.accuracy_m, r.located_at_ms
       FROM jsonb_to_recordset($2::jsonb) AS r(window_start_ms bigint, window_wall_ms bigint, window_s real, class text, scores jsonb,
                                               lat double precision, lon double precision, accuracy_m real, located_at_ms bigint)
       ON CONFLICT (session_id, window_start_ms) DO NOTHING`,
      [id.data, JSON.stringify(rows)],
    );
    const inserted = ins.rowCount ?? 0;
    return c.json({ received: rows.length, inserted, duplicates: rows.length - inserted });
  });

  /** 生データを S3 へ直接 PUT するための署名付き URL。ファイルは API を通さない(Lambda は 6 MB を超えて受けられない) */
  app.post("/sessions/:id/raw-upload-url", async (c) => {
    const id = sessionIdParam.safeParse(c.req.param("id"));
    if (!id.success) return c.json({ error: "invalid_session_id" }, 400);
    const exists = await pool.query("SELECT 1 FROM sessions WHERE id = $1", [id.data]);
    if (exists.rowCount === 0) return c.json({ error: "session_not_found" }, 404);
    const key = rawKey(id.data);
    return c.json({ method: "PUT", url: await storage.presignPut(key), key, expires_in_s: config.UPLOAD_URL_TTL_S });
  });

  /** アップロードの完了通知。置かれたファイルの大きさが申告と合うことを確かめてから記録する */
  app.post("/sessions/:id/raw-complete", async (c) => {
    const id = sessionIdParam.safeParse(c.req.param("id"));
    if (!id.success) return c.json({ error: "invalid_session_id" }, 400);
    const b = await parseBody(c, rawCompleteBody);
    if (!b.ok) return b.res;
    const exists = await pool.query("SELECT 1 FROM sessions WHERE id = $1", [id.data]);
    if (exists.rowCount === 0) return c.json({ error: "session_not_found" }, 404);
    const key = rawKey(id.data);
    const size = await storage.headSize(key);
    if (size === null) return c.json({ error: "object_not_found" }, 409);
    if (size !== b.data.size_bytes) return c.json({ error: "size_mismatch", stored: size, declared: b.data.size_bytes }, 409);
    await pool.query(
      `INSERT INTO raw_files (session_id, object_key, size_bytes, sha256) VALUES ($1, $2, $3, $4)
       ON CONFLICT (session_id) DO UPDATE SET object_key = EXCLUDED.object_key, size_bytes = EXCLUDED.size_bytes,
         sha256 = EXCLUDED.sha256, uploaded_at = now()`,
      [id.data, key, size, b.data.sha256],
    );
    return c.json({ key, size_bytes: size });
  });

  return app;
}
