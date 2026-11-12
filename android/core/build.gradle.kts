import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("org.jetbrains.kotlin.jvm")
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    // Samma JSON-API som finns inbyggt i Android.
    compileOnly("org.json:json:20240303")
    testImplementation("org.json:json:20240303")
    testImplementation("junit:junit:4.13.2")
}
