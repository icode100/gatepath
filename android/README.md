# GatePath Android wrapper

This directory contains a native Android launcher for the production GatePath PWA at
`https://gatepath.vercel.app/`. It uses Android Browser Helper to open the site as a
Trusted Web Activity (TWA), while keeping the React, FastAPI and Firebase application
as the single product implementation.

The package ID is `com.icode100.gatepath`. The wrapper deliberately contains no
production signing key, keystore password or Play Console credential.

## Why this wrapper is needed for themed icons

A Chrome-installed WebAPK does not reliably carry a web manifest's `monochrome` icon
into every Android launcher. A native Android package can supply the platform resources
directly:

- `mipmap-anydpi-v26/` contains the adaptive color icon for Android 8-12.
- `mipmap-anydpi-v33/` adds a true one-color `<monochrome>` layer for Android 13+.
- The Route-G artwork stays inside Android's 66dp safe zone, so Pixel, Samsung and
  other launchers can apply their own masks without clipping it.
- `mipmap-anydpi/` provides a vector fallback for Android 6-7.

On a Pixel running Android 13 or later, enable **Wallpaper & style -> Themed icons**.
On a supported Samsung device, enable **Wallpaper and style -> Color palette -> Apply
palette to app icons**. Launcher/One UI support still controls the final appearance;
the app now provides the native resource launchers require.

Uninstall the Chrome-installed GatePath PWA before installing the native APK, otherwise
the launcher will show two GatePath entries and the WebAPK copy may remain unthemed.

## Prerequisites

- Android Studio with JDK 17 selected for Gradle.
- Android SDK Platform 35 and its build tools.
- An Android 13+ phone or emulator for themed-icon verification.
- Chrome (or another browser with Trusted Web Activity support).

The current workstation only exposes Java 8 and no Android SDK, so the APK/AAB cannot
be compiled here until Android Studio/JDK 17 is installed.

## Build a debug APK

Open this `android` directory in Android Studio and allow Gradle sync to finish, or run:

```powershell
Set-Location android
$env:JAVA_HOME = 'C:\Path\To\Android Studio\jbr'
.\gradlew.bat assembleDebug
```

The APK is written to `app\build\outputs\apk\debug\app-debug.apk`. Install it with:

```powershell
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
```

## Digital Asset Links (required for a full-screen TWA)

Android icon theming works as soon as the APK is installed. Full-screen TWA verification
also requires the website to trust the exact certificate that signed the installed APK.
Without it, GatePath safely opens as a Custom Tab with browser controls.

1. Find the debug certificate fingerprint:

   ```powershell
   keytool -list -v `
     -alias androiddebugkey `
     -keystore "$env:USERPROFILE\.android\debug.keystore" `
     -storepass android `
     -keypass android
   ```

2. Copy the `SHA256:` value and generate the public statement:

   ```powershell
   .\scripts\write-assetlinks.ps1 `
     -Fingerprint 'AA:BB:CC:...:FF'
   ```

3. Commit and deploy the generated `public/.well-known/assetlinks.json`, then verify that
   `https://gatepath.vercel.app/.well-known/assetlinks.json` returns HTTP 200 as JSON with
   no redirect.

The helper accepts multiple `-Fingerprint` values, which is useful while testing both a
debug build and a release build.

## Release signing and Google Play

Use **Build -> Generate Signed Bundle / APK** in Android Studio to create an Android App
Bundle. Store the release keystore outside this repository and keep its passwords in a
password manager or CI secrets.

If Google Play App Signing is enabled, the fingerprint users receive is the **App signing
key certificate** from Play Console, not normally the local upload-key fingerprint. Add
the Play fingerprint to `assetlinks.json` before production rollout. It is safe to publish
certificate fingerprints; private keys and passwords are not safe to commit.

After changing the deployed statement, reinstall/clear verification state and check:

```powershell
adb shell pm verify-app-links --re-verify com.icode100.gatepath
adb shell pm get-app-links com.icode100.gatepath
```

The `gatepath.vercel.app` entry should be reported as verified. If it is not, compare the
fingerprint against the certificate on the installed APK or the Play App Signing page.

## Updating the wrapper

- Increase `versionCode` for every Play upload and update `versionName` as appropriate.
- Keep `default_url`, the HTTPS intent filter and the website's Digital Asset Links file
  aligned if the production hostname changes.
- The web app manifest remains available at
  `https://gatepath.vercel.app/manifest.webmanifest`; native launcher layers in this
  directory are intentionally the source of truth for Android icon theming.

