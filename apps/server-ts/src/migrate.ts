import { loadConfig } from "./config.js";
import { createPool, migrate } from "./db.js";

const config = loadConfig();
const pool = createPool(config.DATABASE_URL);
const applied = await migrate(pool);
console.log(applied.length ? `適用: ${applied.join(", ")}` : "適用するマイグレーションはありません");
await pool.end();
