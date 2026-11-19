package roadml.server

import java.net.URI
import java.net.URLDecoder

/** PostgreSQL への接続。DATABASE_URL(postgres://user:pass@host:port/db)から作る */
data class DbConfig(
    val jdbcUrl: String,
    val user: String?,
    val password: String?,
    val poolSize: Int,
    /** テストで search_path を分けて、開発用のデータと混ざらないようにする */
    val schema: String? = null,
)

data class Config(
    val port: Int,
    val apiKey: String,
    val db: DbConfig,
    /** 無ければ本物の AWS の S3(Lambda では、こちら) */
    val s3Endpoint: URI?,
    /** 署名にはホストが含まれるので、クライアントから見える名前で署名する(PC は 127.0.0.1、エミュレーターは 10.0.2.2) */
    val s3PublicEndpoint: URI?,
    val s3Bucket: String,
    /** 無ければ、AWS の既定の認証情報(Lambda の実行ロール)を使う */
    val s3AccessKey: String?,
    val s3SecretKey: String?,
    val s3Region: String,
    /** 署名付き URL の有効期限 [秒]。走行後の自動送信は再試行が入るので、余裕を持たせる */
    val uploadUrlTtlS: Long,
    val migrationsDir: String,
) {
    companion object {
        fun load(env: Map<String, String>): Config {
            val errors = mutableListOf<String>()
            fun req(name: String, check: (String) -> Boolean = { it.isNotEmpty() }, hint: String = "必須"): String {
                val v = env[name]
                if (v == null || !check(v)) errors += "$name: $hint"
                return v ?: ""
            }
            fun int(name: String, default: Long): Long {
                val v = env[name] ?: return default
                val n = v.toLongOrNull()
                if (n == null || n <= 0) errors += "$name: 正の整数"
                return n ?: default
            }
            fun url(name: String): URI? {
                val v = env[name]?.takeIf { it.isNotEmpty() } ?: return null
                return runCatching { URI(v).also { require(it.scheme in setOf("http", "https") && it.host != null) } }
                    .getOrElse { errors += "$name: http(s) の URL"; null }
            }

            val port = int("PORT", 8787)
            val apiKey = req("API_KEY", { it.length >= 8 }, "8 文字以上")
            val dbUrl = req("DATABASE_URL")
            val poolSize = int("DB_POOL_SIZE", 5)
            val db = runCatching { parseDatabaseUrl(dbUrl, poolSize.toInt()) }.getOrElse {
                if (dbUrl.isNotEmpty()) errors += "DATABASE_URL: postgres://user:pass@host:port/db の形"
                DbConfig("", null, null, 1)
            }
            val endpoint = url("S3_ENDPOINT")
            val publicEndpoint = url("S3_PUBLIC_ENDPOINT") ?: endpoint
            val bucket = req("S3_BUCKET", { it.length >= 3 }, "3 文字以上")
            val accessKey = env["S3_ACCESS_KEY"]?.takeIf { it.isNotEmpty() }
            val secretKey = env["S3_SECRET_KEY"]?.takeIf { it.isNotEmpty() }
            if ((accessKey == null) != (secretKey == null)) errors += "S3_ACCESS_KEY と S3_SECRET_KEY は両方つけるか、両方つけない"
            val ttl = int("UPLOAD_URL_TTL_S", 3600)

            if (errors.isNotEmpty()) {
                throw IllegalStateException("環境変数が足りない、または不正です(.env.example を参照):\n  " + errors.joinToString("\n  "))
            }
            return Config(
                port = port.toInt(), apiKey = apiKey, db = db,
                s3Endpoint = endpoint, s3PublicEndpoint = publicEndpoint, s3Bucket = bucket,
                s3AccessKey = accessKey, s3SecretKey = secretKey,
                s3Region = env["S3_REGION"]?.takeIf { it.isNotEmpty() } ?: "us-east-1",
                uploadUrlTtlS = ttl, migrationsDir = env["MIGRATIONS_DIR"] ?: "migrations",
            )
        }

        /** postgres://user:pass@host:port/db?... を JDBC の URL と認証情報に分ける。jdbc:postgresql:// はそのまま使う */
        fun parseDatabaseUrl(url: String, poolSize: Int): DbConfig {
            if (url.startsWith("jdbc:postgresql://")) return DbConfig(url, null, null, poolSize)
            val u = URI(url)
            require(u.scheme == "postgres" || u.scheme == "postgresql") { "scheme" }
            requireNotNull(u.host) { "host" }
            val (user, password) = (u.rawUserInfo ?: "").split(":", limit = 2).map { URLDecoder.decode(it, Charsets.UTF_8) }
                .let { (it.getOrNull(0)?.takeIf { s -> s.isNotEmpty() }) to it.getOrNull(1) }
            val port = if (u.port > 0) ":${u.port}" else ""
            val query = u.rawQuery?.let { "?$it" } ?: ""
            return DbConfig("jdbc:postgresql://${u.host}$port${u.rawPath}$query", user, password, poolSize)
        }
    }
}
