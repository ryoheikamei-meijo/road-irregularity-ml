import { S3Client, PutObjectCommand, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
const [,, key] = process.argv;
const s3 = new S3Client({ forcePathStyle: true });   // AWS_ENDPOINT_URL を SDK が読む
const put = await getSignedUrl(s3, new PutObjectCommand({ Bucket: "spike-raw", Key: key }), { expiresIn: 900 });
const get = await getSignedUrl(s3, new GetObjectCommand({ Bucket: "spike-raw", Key: key }), { expiresIn: 900 });
console.log(JSON.stringify({ put, get }));
