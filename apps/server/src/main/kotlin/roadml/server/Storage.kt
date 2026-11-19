package roadml.server

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials
import software.amazon.awssdk.auth.credentials.AwsCredentialsProvider
import software.amazon.awssdk.auth.credentials.DefaultCredentialsProvider
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider
import software.amazon.awssdk.core.checksums.RequestChecksumCalculation
import software.amazon.awssdk.core.checksums.ResponseChecksumValidation
import software.amazon.awssdk.core.sync.RequestBody
import software.amazon.awssdk.http.urlconnection.UrlConnectionHttpClient
import software.amazon.awssdk.regions.Region
import software.amazon.awssdk.services.s3.S3Client
import software.amazon.awssdk.services.s3.S3Configuration
import software.amazon.awssdk.services.s3.model.S3Exception
import software.amazon.awssdk.services.s3.presigner.S3Presigner
import java.time.Duration

interface Storage {
    /** 生データを PUT するための署名付き URL を返す */
    fun presignPut(key: String): String
    fun presignGet(key: String): String
    /** 保存されたオブジェクトの大きさ。無ければ null */
    fun headSize(key: String): Long?
    fun ensureBucket()
    fun remove(key: String)
    /** 実際に書き込めるようになるまで待つ。S3 互換のストレージ(SeaweedFS)は、起動直後の数秒、最初の PUT が失敗する */
    fun waitWritable(timeoutMs: Long = 60_000)
}

/**
 * S3(または S3 互換のストレージ)。作るだけでは通信しない。
 * AWS SDK の接続は、SnapStart のスナップショットから戻したあとも自動で張り直される(AWS のドキュメント)。
 */
class S3Storage(private val config: Config) : Storage {
    private val credentials: AwsCredentialsProvider =
        if (config.s3AccessKey != null) StaticCredentialsProvider.create(AwsBasicCredentials.create(config.s3AccessKey, config.s3SecretKey))
        else DefaultCredentialsProvider.builder().build()
    private val region = Region.of(config.s3Region)
    private val bucket = config.s3Bucket
    private val ttl = Duration.ofSeconds(config.uploadUrlTtlS)

    private val client: S3Client = S3Client.builder()
        .region(region)
        .credentialsProvider(credentials)
        .httpClient(UrlConnectionHttpClient.create())
        .forcePathStyle(config.s3Endpoint != null)
        // 必要なときだけチェックサムを付ける。既定(常に付ける)だと、S3 互換のストレージ(SeaweedFS)で失敗することがある
        .requestChecksumCalculation(RequestChecksumCalculation.WHEN_REQUIRED)
        .responseChecksumValidation(ResponseChecksumValidation.WHEN_REQUIRED)
        .apply { config.s3Endpoint?.let { endpointOverride(it) } }
        .build()

    private val presigner: S3Presigner = S3Presigner.builder()
        .region(region)
        .credentialsProvider(credentials)
        .serviceConfiguration(S3Configuration.builder().pathStyleAccessEnabled(config.s3PublicEndpoint != null).build())
        .apply { config.s3PublicEndpoint?.let { endpointOverride(it) } }
        .build()

    override fun presignPut(key: String): String = presigner.presignPutObject { r ->
        r.signatureDuration(ttl).putObjectRequest { it.bucket(bucket).key(key) }
    }.url().toString()

    override fun presignGet(key: String): String = presigner.presignGetObject { r ->
        r.signatureDuration(ttl).getObjectRequest { it.bucket(bucket).key(key) }
    }.url().toString()

    override fun headSize(key: String): Long? = try {
        client.headObject { it.bucket(bucket).key(key) }.contentLength()
    } catch (e: S3Exception) {
        if (e.statusCode() == 404) null else throw e
    }

    override fun ensureBucket() {
        try {
            client.headBucket { it.bucket(bucket) }
        } catch (e: S3Exception) {
            client.createBucket { it.bucket(bucket) }
        }
    }

    override fun remove(key: String) {
        client.deleteObject { it.bucket(bucket).key(key) }
    }

    override fun waitWritable(timeoutMs: Long) {
        val deadline = System.currentTimeMillis() + timeoutMs
        val key = ".ready-probe"
        while (true) {
            try {
                client.putObject({ it.bucket(bucket).key(key) }, RequestBody.fromString("ok"))
                client.deleteObject { it.bucket(bucket).key(key) }
                return
            } catch (e: Exception) {
                if (System.currentTimeMillis() > deadline) throw IllegalStateException("ストレージに書き込めない(${timeoutMs} ms 待った): $e", e)
                Thread.sleep(1000)
            }
        }
    }
}
