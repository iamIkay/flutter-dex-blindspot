plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.johnwogu.pilot.nativeapp"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.johnwogu.pilot.nativeapp"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildTypes {
        release {
            // Template default is no R8 shrinking; -Ppilot.minify=true builds the
            // R8 variant to mirror Flutter's default release shrinking.
            isMinifyEnabled = project.findProperty("pilot.minify") == "true"
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}
