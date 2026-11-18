import { randomUUID } from "node:crypto";
import { createApp } from "../src/app.js";
import { loadConfig, type Config } from "../src/config.js";
import { createPool, migrate } from "../src/db.js";
import { createStorage } from "../src/s3.js";

/** compose.yaml で立てた PostgreSQL・S3 互換ストレージに実際につなぐ(.env.example と同じ値) */
export const TEST_ENV: NodeJS.ProcessEnv = {
  API_KEY: "test-shared-key",
  DATABASE_URL: "postgres://roadml:roadml-dev@127.0.0.1:5433/roadml",
  S3_ENDPOINT: "http://127.0.0.1:8333",
  S3_PUBLIC_ENDPOINT: "http://127.0.0.1:8333",
  S3_BUCKET: "roadml-raw-test",
  S3_ACCESS_KEY: "roadml-dev",
  S3_SECRET_KEY: "roadml-dev-secret",
};

export async function setup() {
  const config: Config = loadConfig(TEST_ENV);
  const schema = `test_${randomUUID().replaceAll("-", "").slice(0, 12)}`;
  const admin = createPool(config.DATABASE_URL);
  await admin.query(`CREATE SCHEMA ${schema}`);
  const pool = createPool(config.DATABASE_URL, schema);
  await migrate(pool);
  const storage = createStorage(config);
  await storage.ensureBucket();
  await storage.waitWritable();
  const app = createApp({ config, pool, storage });
  const headers = { "x-api-key": config.API_KEY, "content-type": "application/json" };
  const post = (path: string, body: unknown, h: Record<string, string> = headers) =>
    app.request(path, { method: "POST", headers: h, body: typeof body === "string" ? body : JSON.stringify(body) });
  return {
    config, pool, storage, app, headers, post,
    async teardown() {
      await pool.end();
      await admin.query(`DROP SCHEMA ${schema} CASCADE`);
      await admin.end();
    },
  };
}

export function newSession(over: Record<string, unknown> = {}) {
  return {
    id: randomUUID(), device_id: "emulator-5554", started_at: "2026-11-18T05:00:00+09:00",
    app_version: "0.1.0", model_version: "v4_20261118", ...over,
  };
}

export function detection(startMs: number, over: Record<string, unknown> = {}) {
  return {
    window_start_ms: startMs, window_s: 2.0, class: "flat", scores: { flat: 1.2, step: -0.4, rough: -0.9 },
    lat: 35.1815, lon: 136.9066, accuracy_m: 8.5, located_at_ms: startMs + 2000, ...over,
  };
}
