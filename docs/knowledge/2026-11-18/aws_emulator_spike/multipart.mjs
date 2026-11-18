import { S3Client, CreateMultipartUploadCommand, UploadPartCommand, CompleteMultipartUploadCommand, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
const [,, file, partMB] = process.argv;
const key = "sessions/test/multipart.bin", Bucket = "spike-raw";
const s3 = new S3Client({ forcePathStyle: true });
const buf = readFileSync(file), size = Number(partMB) * 1048576;
const { UploadId } = await s3.send(new CreateMultipartUploadCommand({ Bucket, Key: key }));
const parts = [];
for (let i = 0, n = 1; i < buf.length; i += size, n++) {
  const url = await getSignedUrl(s3, new UploadPartCommand({ Bucket, Key: key, UploadId, PartNumber: n }), { expiresIn: 900 });
  const chunk = buf.subarray(i, i + size);
  const res = await fetch(url, { method: "PUT", body: chunk });    // NODE_EXTRA_CA_CERTS で証明書を信頼
  if (!res.ok) { console.log(`part ${n} 失敗: ${res.status} ${(await res.text()).slice(0,400)}`); process.exit(1); }
  parts.push({ PartNumber: n, ETag: res.headers.get("etag") });
}
await s3.send(new CompleteMultipartUploadCommand({ Bucket, Key: key, UploadId, MultipartUpload: { Parts: parts } }));
const got = Buffer.from(await (await s3.send(new GetObjectCommand({ Bucket, Key: key }))).Body.transformToByteArray());
const h = (b) => createHash("sha256").update(b).digest("hex").slice(0, 16);
console.log(`parts=${parts.length} 送信=${h(buf)} 取得=${h(got)} 一致=${h(buf) === h(got)} size=${got.length}`);
