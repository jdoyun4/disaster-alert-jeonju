$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceDir = Split-Path -Parent $projectDir
$sdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$buildTools = Join-Path $sdk "build-tools\36.0.0"
$androidJar = Join-Path $sdk "platforms\android-36\android.jar"
$javaHome = "C:\Program Files\Android\Android Studio\jbr"
$env:JAVA_HOME = $javaHome
$env:Path = "$javaHome\bin;$sdk\platform-tools;$env:Path"

$sourceOutputs = Get-ChildItem -Path $env:OneDrive -Recurse -Filter index.html -File |
    Where-Object {
        $_.Directory.Name -eq "outputs" -and
        (Test-Path (Join-Path $_.Directory.FullName "map.html"))
    } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty DirectoryName
if (-not $sourceOutputs) {
    throw "Could not find the unified app output files."
}

$stage = Join-Path $env:USERPROFILE "disaster_alert_android"
$assets = Join-Path $stage "assets"
$build = Join-Path $stage "build"
$classes = Join-Path $build "classes"
$generated = Join-Path $build "generated"
$dex = Join-Path $build "dex"
$stageRes = Join-Path $stage "res"
$stageSrc = Join-Path $stage "src"
$stageManifest = Join-Path $stage "AndroidManifest.xml"

New-Item -ItemType Directory -Force -Path $stage, $assets, $build, $classes, $generated, $dex | Out-Null
Copy-Item -LiteralPath (Join-Path $projectDir "res") -Destination $stage -Recurse -Force
Copy-Item -LiteralPath (Join-Path $projectDir "src") -Destination $stage -Recurse -Force
Copy-Item -LiteralPath (Join-Path $projectDir "AndroidManifest.xml") -Destination $stageManifest -Force
Copy-Item -LiteralPath (Join-Path $sourceOutputs "index.html") -Destination (Join-Path $assets "index.html") -Force
Copy-Item -LiteralPath (Join-Path $sourceOutputs "map.html") -Destination (Join-Path $assets "map.html") -Force

& (Join-Path $buildTools "aapt2.exe") compile `
    --dir $stageRes `
    -o (Join-Path $build "resources.zip")
if ($LASTEXITCODE -ne 0) { throw "Resource compilation failed." }

& (Join-Path $buildTools "aapt2.exe") link `
    -o (Join-Path $build "unsigned.apk") `
    -I $androidJar `
    --min-sdk-version 26 `
    --target-sdk-version 36 `
    --version-code 5 `
    --version-name "2.1.0" `
    --manifest $stageManifest `
    --java $generated `
    -A $assets `
    (Join-Path $build "resources.zip")
if ($LASTEXITCODE -ne 0) { throw "APK resource linking failed." }

$javaSources = Get-ChildItem -Path $stageSrc -Recurse -Filter *.java | ForEach-Object FullName
$generatedSources = Get-ChildItem -Path $generated -Recurse -Filter *.java | ForEach-Object FullName
& (Join-Path $javaHome "bin\javac.exe") `
    -encoding UTF-8 `
    -source 11 `
    -target 11 `
    -classpath $androidJar `
    -d $classes `
    $javaSources `
    $generatedSources
if ($LASTEXITCODE -ne 0) { throw "Java compilation failed." }

& (Join-Path $javaHome "bin\jar.exe") cf (Join-Path $build "classes.jar") -C $classes .
if ($LASTEXITCODE -ne 0) { throw "Class packaging failed." }
& (Join-Path $buildTools "d8.bat") `
    --lib $androidJar `
    --output $dex `
    (Join-Path $build "classes.jar")
if ($LASTEXITCODE -ne 0) { throw "DEX generation failed." }
& (Join-Path $javaHome "bin\jar.exe") uf (Join-Path $build "unsigned.apk") -C $dex classes.dex
if ($LASTEXITCODE -ne 0) { throw "DEX insertion failed." }

& (Join-Path $buildTools "zipalign.exe") `
    -f 4 `
    (Join-Path $build "unsigned.apk") `
    (Join-Path $build "aligned.apk")
if ($LASTEXITCODE -ne 0) { throw "APK alignment failed." }

$keyStore = Join-Path $stage "disaster-alert-debug.keystore"
if (-not (Test-Path $keyStore)) {
    & (Join-Path $javaHome "bin\keytool.exe") `
        -genkeypair `
        -keystore $keyStore `
        -storepass android `
        -keypass android `
        -alias disasteralert `
        -keyalg RSA `
        -keysize 2048 `
        -validity 10000 `
        -dname "CN=Disaster Alert, OU=Personal, O=Personal, L=Jeonju, C=KR"
    if ($LASTEXITCODE -ne 0) { throw "Signing key generation failed." }
}

$apk = Join-Path $build "disaster-alert.apk"
& (Join-Path $buildTools "apksigner.bat") sign `
    --ks $keyStore `
    --ks-key-alias disasteralert `
    --ks-pass pass:android `
    --key-pass pass:android `
    --out $apk `
    (Join-Path $build "aligned.apk")
if ($LASTEXITCODE -ne 0) { throw "APK signing failed." }

$adb = Join-Path $sdk "platform-tools\adb.exe"
$device = & $adb devices | Select-String "\sdevice$" | Select-Object -First 1
if ($device) {
    & $adb install -r $apk
    if ($LASTEXITCODE -eq 0) {
        & $adb shell am start -n kr.co.disasteralert/.MainActivity
        if ($LASTEXITCODE -ne 0) { throw "App launch failed." }
    } else {
        & $adb push $apk "/sdcard/Download/disaster-alert.apk"
        if ($LASTEXITCODE -ne 0) { throw "APK transfer failed." }
        Write-Host "Automatic installation was blocked. APK copied to Download."
    }
} else {
    Write-Host "No Android device connected. APK build completed without installation."
}

Write-Host "APK: $apk"
