const mods = ["node:net","node:tls","node:crypto","node:util","node:util/types","util/types","node:stream","node:events","node:dns","node:fs","node:buffer","node:string_decoder","node:os","node:zlib","node:http","node:https","node:url","node:path","node:perf_hooks","node:worker_threads"];
export const handler = async () => {
  const out = {};
  for (const m of mods) { try { await import(m); out[m] = "ok"; } catch (e) { out[m] = "NG: " + String(e.message).slice(0, 60); } }
  out.version = process.version; out.versions = Object.keys(process.versions ?? {}).slice(0, 8);
  try { out.fetch = typeof fetch; } catch {}
  return out;
};
