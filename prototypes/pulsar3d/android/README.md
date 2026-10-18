# PULSAR 3D — Android APK

`build_apk.py` turns the web game into an **offline** Android app: a full-screen
WebView (`src/com/pulsar3d/game/MainActivity.java`). Three.js, the fonts and the
GLB models are all bundled inside the APK and served from a private https origin,
`appassets.androidplatform.net`, so ES modules and `fetch()` work without internet.

- **Package:** `com.pulsar3d.game`. minSdk 24 (Android 7), targetSdk 34.
- **Behaviour:** immersive full screen and automatic rotation. Back pauses the game;
  pressing it twice exits. Leaving the app pauses and mutes the game.
- **No Android SDK or Gradle needed.** The tools are:
  - aapt2, from the npm package `aaptjs3`
  - `android.jar` API 30
  - `dalvik-dx`, from Maven Central
  - `apk_sign_ts`, which signs v1 + v2 + v3 and zipaligns

## Build

```bash
AAPT2=... ANDROID_JAR=... DX_JAR=... THREE_DIR=.../node_modules/three \
FONTS_DIR=... SIGNER_DIR=... KEY_PEM=key.pem CERT_PEM=cert.pem ICON_SRC=icon.png \
python3 build_apk.py Pulsar3D.apk --version-code 1 --version-name 1.0
```

The header of `build_apk.py` documents each variable.

## Verification done

- `aapt2 dump badging` reads the package correctly.
- `apksig` reports `verified=true`, with the v2 scheme. v1 is not checked at
  minSdk 24.
- Stored entries are 4-byte aligned.
- The game extracted from the APK runs in Chromium with all network requests
  blocked: fonts and models load, and there are 0 errors.

**Not verified here:** installation and gameplay on a real phone. There is no
Android emulator in the build environment.

**Signing key.** The test APK is signed with a self-signed key that was generated
on the fly and not saved to the repo. A future build with a different key will not
install as an update: uninstall the old app first. For a store release, create
your own keystore and keep it safe.
