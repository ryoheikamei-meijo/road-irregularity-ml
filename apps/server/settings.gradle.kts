plugins {
    // JDK 21 が手元に無ければ、Gradle が ~/.gradle/jdks に取ってくる(http4k 6 と Lambda の java21 に合わせる)
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
}

rootProject.name = "roadml-server"

dependencyResolutionManagement {
    repositories { mavenCentral() }
}
