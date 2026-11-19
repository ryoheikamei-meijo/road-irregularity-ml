package roadml.server

import com.zaxxer.hikari.HikariConfig
import com.zaxxer.hikari.HikariDataSource
import java.io.File
import java.sql.Connection
import java.sql.PreparedStatement
import java.sql.Types

/**
 * PostgreSQL への接続。**初めて使うときにつなぐ**(作っただけではつながない)。
 *
 * Lambda の SnapStart は、初期化が終わった時点のメモリをスナップショットにして、そこから起動する。
 * 初期化中に張った接続は、戻したあとに使えるとは限らない(AWS のドキュメント)。そのため、接続はリクエストを受けてから張り、
 * スナップショットに接続を含めない。
 */
class Database(private val config: DbConfig) : AutoCloseable {
    private val lazySource = lazy {
        HikariDataSource(HikariConfig().apply {
            jdbcUrl = config.jdbcUrl
            config.user?.let { username = it }
            config.password?.let { password = it }
            maximumPoolSize = config.poolSize
            minimumIdle = 0
            config.schema?.let { schema = it }
            poolName = "roadml"
        })
    }

    fun <T> withConnection(block: (Connection) -> T): T = lazySource.value.connection.use(block)

    /** 1 文を流し、変わった行数を返す */
    fun update(sql: String, vararg params: Any?): Int = withConnection { c -> c.prepareStatement(sql).use { it.bind(params).executeUpdate() } }

    /** 1 文を流し、各行を変換して返す */
    fun <T> query(sql: String, vararg params: Any?, row: (java.sql.ResultSet) -> T): List<T> = withConnection { c ->
        c.prepareStatement(sql).use { st ->
            st.bind(params).executeQuery().use { rs -> buildList { while (rs.next()) add(row(rs)) } }
        }
    }

    override fun close() {
        if (lazySource.isInitialized()) lazySource.value.close()
    }
}

/** null は型を決めずに渡す(SQL の側で ?::uuid などと型を付ける) */
fun PreparedStatement.bind(params: Array<out Any?>): PreparedStatement {
    params.forEachIndexed { i, v -> if (v == null) setNull(i + 1, Types.NULL) else setObject(i + 1, v) }
    return this
}

/** migrations の .sql を名前順に、未適用のものだけ流す。適用済みは schema_migrations に残る(TypeScript 版と同じ表なので、DB を共有できる) */
fun migrate(db: Database, dir: File): List<String> = db.withConnection { c ->
    c.createStatement().use { it.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())") }
    val done = c.createStatement().use { st -> st.executeQuery("SELECT name FROM schema_migrations").use { rs -> buildSet { while (rs.next()) add(rs.getString(1)) } } }
    val files = (dir.listFiles { f -> f.name.endsWith(".sql") } ?: error("マイグレーションのフォルダが無い: ${dir.absolutePath}")).sortedBy { it.name }
    val applied = mutableListOf<String>()
    for (f in files) {
        if (f.name in done) continue
        c.autoCommit = false
        try {
            c.createStatement().use { it.execute(f.readText()) }
            c.prepareStatement("INSERT INTO schema_migrations (name) VALUES (?)").use { it.setString(1, f.name); it.executeUpdate() }
            c.commit()
        } catch (e: Exception) {
            c.rollback()
            throw e
        } finally {
            c.autoCommit = true
        }
        applied += f.name
    }
    applied
}
