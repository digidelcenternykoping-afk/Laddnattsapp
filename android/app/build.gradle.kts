plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Signeringsnyckeln kommer från GitHubs hemligheter vid bygge. Utan den signeras
// appen med en tillfällig testnyckel (går att installera men inte att uppdatera).
val keystorePath: String? = System.getenv("KEYSTORE_FILE")?.takeIf { it.isNotBlank() }

android {
    namespace = "se.laddnatt.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "se.laddnatt.app"
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("VERSION_CODE") ?: "1").toInt()
        versionName = "0.$versionCode"
    }

    signingConfigs {
        if (keystorePath != null) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = "laddnatt"
                keyPassword = System.getenv("KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName(if (keystorePath != null) "release" else "debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        buildConfig = true
    }
    lint {
        checkReleaseBuilds = false
    }
}

dependencies {
    implementation(project(":core"))
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.work:work-runtime:2.9.1")
}
