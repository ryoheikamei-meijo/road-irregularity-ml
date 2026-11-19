package roadml.server

import org.eclipse.jetty.server.ServerConnector
import org.http4k.server.Jetty
import org.http4k.server.asServer
import java.io.File

/** PC(と研究室のサーバー)で動かす入口。`./gradlew run` */
fun main() {
    val config = Config.load(System.getenv())
    val db = Database(config.db)
    val storage = S3Storage(config)
    val applied = migrate(db, File(config.migrationsDir))
    if (applied.isNotEmpty()) println("マイグレーションを適用: ${applied.joinToString()}")
    storage.ensureBucket()
    storage.waitWritable()
    // 127.0.0.1 だけで待ち受ける。エミュレーター(10.0.2.2)から届かせるときは HOST=0.0.0.0 にする(共有キーしか守りが無いので、普段はしない)
    val host = System.getenv("HOST") ?: "127.0.0.1"
    val server = createApp(Deps(config, db, storage))
        .asServer(Jetty(config.port, { s -> ServerConnector(s).apply { this.host = host; this.port = config.port } }))
        .start()
    println("listening on http://$host:${server.port()}")
    Runtime.getRuntime().addShutdownHook(Thread { server.stop(); db.close() })
    server.block()
}
