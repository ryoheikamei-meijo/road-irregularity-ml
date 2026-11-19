plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

// アプリに入れるモデルの版。models/<版>/ の中身(core_svm.onnx・model_info.json・replay/)を、そのままアセットにする
val modelVersion: String = providers.gradleProperty("roaddetector.modelVersion").get()
val modelDir: File = rootProject.file("models/$modelVersion")
val apiUrl: String = providers.gradleProperty("roaddetector.apiUrl").get()
val apiKey: String = providers.gradleProperty("roaddetector.apiKey").get()
val mapStyleUrl: String = providers.gradleProperty("roaddetector.mapStyleUrl").get()
require(modelDir.resolve("core_svm.onnx").isFile) { "モデルが無い: $modelDir/core_svm.onnx" }

android {
    namespace = "com.example.roaddetector"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.roaddetector"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        // ONNX Runtime のネイティブライブラリを、ほとんどのスマホ(と Apple Silicon のエミュレーター)が使う arm64 だけにする
        ndk { abiFilters += listOf("arm64-v8a") }
        buildConfigField("String", "API_URL", "\"$apiUrl\"")
        buildConfigField("String", "API_KEY", "\"$apiKey\"")
        buildConfigField("String", "MAP_STYLE_URL", "\"$mapStyleUrl\"")
    }
    buildFeatures { buildConfig = true }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    sourceSets["main"].assets.srcDir(modelDir)
    testOptions {
        unitTests.all {
            // 単体テストで、研究リポジトリの生データ(wheelchair_data)と PC の判定結果(data/analysis)を読む
            it.systemProperty("repoRoot", rootProject.projectDir.parentFile.parentFile.absolutePath)
            it.systemProperty("modelDir", modelDir.absolutePath)
            // モデルや PC の正解が変わったら、テストをやり直す
            it.inputs.dir(modelDir)
            it.inputs.dir(rootProject.projectDir.parentFile.parentFile.resolve("data/analysis/20261116_export_onnx/parity")).optional()
            it.testLogging { events("passed", "skipped", "failed", "standardOut"); showStandardStreams = true }
            it.maxHeapSize = "2g"
        }
    }
}

// 単体テスト(PC の JVM)では、Android 版の onnxruntime の代わりに PC 版を使う(クラス名が同じため)
configurations.matching { it.name.endsWith("UnitTestRuntimeClasspath") }.configureEach {
    exclude(group = "com.microsoft.onnxruntime", module = "onnxruntime-android")
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.work.runtime)
    implementation(libs.onnxruntime.android)
    implementation(libs.maplibre.android)
    testImplementation(libs.junit)
    testImplementation(libs.org.json)
    testImplementation(libs.onnxruntime.jvm)
}
