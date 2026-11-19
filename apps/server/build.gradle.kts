plugins {
    kotlin("jvm") version "2.4.21"
    application
}

// Lambda の java21 ランタイムに合わせる(http4k 6 も Java 21 が要る)
kotlin { jvmToolchain(21) }

dependencies {
    implementation(platform("org.http4k:http4k-bom:6.61.0.0"))
    implementation("org.http4k:http4k-core")
    implementation("org.http4k:http4k-server-jetty")
    implementation("org.http4k:http4k-serverless-lambda")

    implementation(platform("software.amazon.awssdk:bom:2.59.3"))
    implementation("software.amazon.awssdk:s3") {
        // HTTP クライアントは JDK の HttpURLConnection を使う軽いものだけにする(Lambda の起動とパッケージを軽くする)
        exclude(group = "software.amazon.awssdk", module = "netty-nio-client")
        exclude(group = "software.amazon.awssdk", module = "apache-client")
    }
    implementation("software.amazon.awssdk:url-connection-client")

    implementation("org.postgresql:postgresql:42.7.14")
    implementation("com.zaxxer:HikariCP:7.1.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.13.0")
    runtimeOnly("org.slf4j:slf4j-simple:2.0.20")

    testImplementation(kotlin("test"))
    testImplementation(platform("org.junit:junit-bom:6.1.3"))
    testImplementation("org.junit.jupiter:junit-jupiter")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

application { mainClass = "roadml.server.MainKt" }

/** .env を読む(npm 版の --env-file-if-exists と同じく、すでにある環境変数は上書きしない) */
fun dotenv(): Map<String, String> {
    val f = file(".env")
    if (!f.exists()) return emptyMap()
    return f.readLines().map { it.trim() }
        .filter { it.isNotEmpty() && !it.startsWith("#") && "=" in it }
        .associate { it.substringBefore("=").trim() to it.substringAfter("=").trim() }
        .filterKeys { System.getenv(it) == null }
}

tasks.named<JavaExec>("run") { environment(dotenv()) }

tasks.register<JavaExec>("migrate") {
    group = "application"
    description = "migrations/*.sql のうち未適用のものを流す"
    classpath = sourceSets.main.get().runtimeClasspath
    mainClass = "roadml.server.MigrateKt"
    environment(dotenv())
}

tasks.test {
    useJUnitPlatform()
    // 同じ DB・同じストレージを使うので、1 つずつ流す
    maxParallelForks = 1
    testLogging { events("passed", "failed", "skipped"); exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL }
}

/** Lambda に上げる zip(クラスは直下、依存は lib/)。AWS の Java 向けの手順と同じ形 */
tasks.register<Zip>("lambdaZip") {
    group = "build"
    description = "Lambda(java21・SnapStart)に上げる zip を build/distributions に作る"
    archiveFileName = "roadml-server-lambda.zip"
    from(tasks.compileKotlin, tasks.processResources)
    into("lib") { from(configurations.runtimeClasspath) }
}
