import { z } from "zod";

export const CLASSES = ["flat", "step", "rough"] as const;

export const sessionBody = z.object({
  id: z.uuid(),
  device_id: z.string().min(1).max(128),
  started_at: z.iso.datetime({ offset: true }),
  app_version: z.string().min(1).max(64),
  model_version: z.string().min(1).max(64),
  wheelchair: z.string().max(128).optional(),
  weight_kg: z.number().positive().max(500).optional(),
});

export const detectionItem = z
  .object({
    window_start_ms: z.number().int().nonnegative(),
    window_wall_ms: z.number().int().nonnegative().optional(),
    window_s: z.number().positive().max(60),
    class: z.enum(CLASSES),
    scores: z.object({ flat: z.number(), step: z.number(), rough: z.number() }),
    lat: z.number().min(-90).max(90).optional(),
    lon: z.number().min(-180).max(180).optional(),
    accuracy_m: z.number().nonnegative().optional(),
    located_at_ms: z.number().int().nonnegative().optional(),
  })
  .refine((d) => (d.lat === undefined) === (d.lon === undefined), { message: "lat と lon は両方つけるか、両方つけない" });

/** 1 回のバッチの上限。数秒ごとに送るので 2 窓/秒 × 数十秒でも余裕がある。再送でためた分も入るように大きめにする */
export const MAX_BATCH = 2000;
export const detectionsBody = z.object({ detections: z.array(detectionItem).min(1).max(MAX_BATCH) });

export const rawCompleteBody = z.object({
  size_bytes: z.number().int().positive(),
  sha256: z.string().regex(/^[0-9a-f]{64}$/, "sha256 は小文字の 16 進 64 桁"),
});

export const sessionIdParam = z.uuid();
