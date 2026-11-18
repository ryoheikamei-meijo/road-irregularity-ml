import pg from "pg";
export const handler = async (event) => {
  const host = event.host ?? "host.docker.internal";
  const c = new pg.Client({ host, port: 5433, user: "postgres", password: "spike", database: "spike", connectionTimeoutMillis: 3000 });
  try {
    await c.connect();
    await c.query("create table if not exists t(id int primary key, v text)");
    await c.query("insert into t values (1,'a') on conflict do nothing");
    const r = await c.query("select count(*)::int as n, version() as v from t");
    return { ok: true, host, n: r.rows[0].n, version: r.rows[0].v.slice(0, 40) };
  } catch (e) {
    return { ok: false, host, error: String(e.message).slice(0, 200) };
  } finally { await c.end().catch(() => {}); }
};
