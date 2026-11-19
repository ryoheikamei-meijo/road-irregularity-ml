import { serve } from "@hono/node-server";
import { createApp } from "./app.js";
import { loadConfig } from "./config.js";
import { createPool, migrate } from "./db.js";
import { createStorage } from "./s3.js";

const config = loadConfig();
const pool = createPool(config.DATABASE_URL);
const storage = createStorage(config);
await migrate(pool);
await storage.ensureBucket();
await storage.waitWritable();
// 127.0.0.1 だけで待ち受ける。エミュレーター(10.0.2.2)から届かせるときは HOST=0.0.0.0 にする(共有キーしか守りが無いので、普段はしない)
const hostname = process.env["HOST"] ?? "127.0.0.1";
serve({ fetch: createApp({ config, pool, storage }).fetch, port: config.PORT, hostname }, (info) => {
  console.log(`listening on http://${info.address}:${info.port}`);
});
