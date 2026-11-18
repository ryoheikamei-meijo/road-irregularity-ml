import { CreateBucketCommand, DeleteObjectCommand, GetObjectCommand, HeadBucketCommand, HeadObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import type { Config } from "./config.js";

export interface Storage {
  /** 生データを PUT するための署名付き URL を返す */
  presignPut(key: string): Promise<string>;
  /** 保存されたオブジェクトの大きさ。無ければ null */
  headSize(key: string): Promise<number | null>;
  ensureBucket(): Promise<void>;
  remove(key: string): Promise<void>;
  /** 実際に書き込めるようになるまで待つ。S3 互換のストレージ(SeaweedFS)は、起動直後の数秒、書き込みの内部ロックの準備ができず、最初の PUT が失敗する */
  waitWritable(timeoutMs?: number): Promise<void>;
  presignGet(key: string): Promise<string>;
}

function client(config: Config, endpoint: string): S3Client {
  return new S3Client({
    endpoint,
    region: config.S3_REGION,
    credentials: { accessKeyId: config.S3_ACCESS_KEY, secretAccessKey: config.S3_SECRET_KEY },
    forcePathStyle: true,
    // 署名付き URL に「空のボディのチェックサム」を付けさせない。付くと、S3 互換のストレージ(SeaweedFS)で
    // 400(BadDigest)になる。アプリが PUT するボディと合わなくなるため、必要なときだけ計算させる。
    requestChecksumCalculation: "WHEN_REQUIRED",
    responseChecksumValidation: "WHEN_REQUIRED",
  });
}

export function createStorage(config: Config): Storage {
  const internal = client(config, config.S3_ENDPOINT);
  // 署名にはホストが含まれるので、クライアントから見える名前(S3_PUBLIC_ENDPOINT)で署名する
  const pub = client(config, config.S3_PUBLIC_ENDPOINT);
  const Bucket = config.S3_BUCKET;
  return {
    presignPut: (key) => getSignedUrl(pub, new PutObjectCommand({ Bucket, Key: key }), { expiresIn: config.UPLOAD_URL_TTL_S }),
    presignGet: (key) => getSignedUrl(pub, new GetObjectCommand({ Bucket, Key: key }), { expiresIn: config.UPLOAD_URL_TTL_S }),
    async headSize(key) {
      try {
        const r = await internal.send(new HeadObjectCommand({ Bucket, Key: key }));
        return r.ContentLength ?? null;
      } catch (e) {
        const status = (e as { $metadata?: { httpStatusCode?: number } }).$metadata?.httpStatusCode;
        if (status === 404) return null;
        throw e;
      }
    },
    async remove(key) {
      await internal.send(new DeleteObjectCommand({ Bucket, Key: key }));
    },
    async waitWritable(timeoutMs = 60_000) {
      const deadline = Date.now() + timeoutMs;
      const key = ".ready-probe";
      for (let lastError: unknown; ; ) {
        try {
          await internal.send(new PutObjectCommand({ Bucket, Key: key, Body: "ok" }));
          await internal.send(new DeleteObjectCommand({ Bucket, Key: key }));
          return;
        } catch (e) {
          lastError = e;
          if (Date.now() > deadline) throw new Error(`ストレージに書き込めない(${timeoutMs} ms 待った): ${String(lastError)}`);
          await new Promise((r) => setTimeout(r, 1000));
        }
      }
    },
    async ensureBucket() {
      try {
        await internal.send(new HeadBucketCommand({ Bucket }));
      } catch {
        await internal.send(new CreateBucketCommand({ Bucket }));
      }
    },
  };
}
