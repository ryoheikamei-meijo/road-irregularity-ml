package roadml.server

import java.io.File

/** `./gradlew migrate`。本番(Lambda)ではリクエストの中で流さず、デプロイの手順として、これを別に流す */
fun main() {
    val config = Config.load(System.getenv())
    Database(config.db).use { db ->
        val applied = migrate(db, File(config.migrationsDir))
        println(if (applied.isNotEmpty()) "適用: ${applied.joinToString()}" else "適用するマイグレーションはありません")
    }
}
