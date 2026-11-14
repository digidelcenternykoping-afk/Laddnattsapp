pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
    plugins {
        id("com.android.application") version "8.7.3"
        id("org.jetbrains.kotlin.android") version "2.0.21"
        id("org.jetbrains.kotlin.jvm") version "2.0.21"
    }
}
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "laddnattsapp"
include(":core")
// Beslutslogiken (:core) är ren Kotlin och kan testas utan Android SDK:
//   CORE_ONLY=1 gradle :core:test
if (System.getenv("CORE_ONLY") == null) include(":app")
