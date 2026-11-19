import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import pg from "pg";

export function createPool(connectionString: string, searchPath?: string): pg.Pool {
  // テストでは search_path を分けて、開発用のデータと混ざらないようにする
  return new pg.Pool({ connectionString, ...(searchPath ? { options: `-c search_path=${searchPath}` } : {}) });
}

const MIGRATIONS_DIR = fileURLToPath(new URL("../migrations/", import.meta.url));

/** migrations/*.sql を名前順に、未適用のものだけ流す。適用済みは schema_migrations に残る。 */
export async function migrate(pool: pg.Pool): Promise<string[]> {
  const client = await pool.connect();
  const applied: string[] = [];
  try {
    await client.query("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())");
    const done = new Set((await client.query<{ name: string }>("SELECT name FROM schema_migrations")).rows.map((r) => r.name));
    const files = (await readdir(MIGRATIONS_DIR)).filter((f) => f.endsWith(".sql")).sort();
    for (const f of files) {
      if (done.has(f)) continue;
      const sql = await readFile(MIGRATIONS_DIR + f, "utf-8");
      await client.query("BEGIN");
      try {
        await client.query(sql);
        await client.query("INSERT INTO schema_migrations (name) VALUES ($1)", [f]);
        await client.query("COMMIT");
      } catch (e) {
        await client.query("ROLLBACK");
        throw e;
      }
      applied.push(f);
    }
  } finally {
    client.release();
  }
  return applied;
}
