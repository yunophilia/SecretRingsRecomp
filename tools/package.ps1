# Collects a playable build into dist/SecretRingsRecomp (no game data is included).
#   powershell -ExecutionPolicy Bypass -File tools/package.ps1
# On first run the exe asks for the player's disc image and installs the data into game/.
$root = Split-Path $PSScriptRoot
$dist = Join-Path $root "dist\SecretRingsRecomp"
$exe = Join-Path $root "out\SecretRingsRecomp.exe"
if (-not (Test-Path $exe)) { throw "build first (cmake --build --preset windows-clang)" }
New-Item -ItemType Directory -Force $dist | Out-Null
New-Item -ItemType Directory -Force (Join-Path $dist "game") | Out-Null
Copy-Item $exe $dist -Force
Copy-Item (Join-Path $root "README.md") $dist -Force
Copy-Item (Join-Path $root "LICENSE") $dist -Force   # GPL-2.0: the licence travels with the binary
# Ship a precompiled shader cache: the GX states recorded in data/shadercache (plus any the
# development build has seen in out/shadercache), compiled here with Microsoft's HLSL
# compiler. A fresh install then does not compile on first play, and under Wine/Proton the
# game does not depend on Wine's own HLSL compiler for these shaders.
$dstCache = Join-Path $dist "shadercache"
New-Item -ItemType Directory -Force $dstCache | Out-Null
Get-ChildItem $dstCache -Filter *.cso | Remove-Item   # blobs of an earlier package; rebuilt below
foreach ($k in "vs_keys.bin", "ps_keys.bin") {
    $bytes = [byte[]]@()
    foreach ($src in (Join-Path $root "data\shadercache\$k"), (Join-Path $root "out\shadercache\$k"), (Join-Path $dstCache $k)) {
        if (Test-Path $src) { $bytes += [IO.File]::ReadAllBytes($src) }
    }
    [IO.File]::WriteAllBytes((Join-Path $dstCache $k), $bytes)   # de-duplicated by the precompile step
}
& $exe --precompile-shaders $dstCache
if ($LASTEXITCODE -ne 0) { throw "shader precompilation failed" }

# Xbox button prompts: the Xbox textures of "HD Xbox One/Series (And PS4/5) GUI and
# Controls" by Accelerate (gamebanana.com/mods/390496, CC BY-NC-ND 4.0), shipped unmodified
# in textures/RSR (all three releases) with its credits. The mod's zip is pinned by file id
# and MD5 and cached in out/ so a package is reproducible.
$promptZip = Join-Path $root "out\gb390496_1756030.zip"
$promptMd5 = "bc53140d85890cda227705c313eb3628"
if (-not (Test-Path $promptZip) -or (Get-FileHash $promptZip -Algorithm MD5).Hash.ToLower() -ne $promptMd5) {
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri "https://gamebanana.com/dl/1756030" -OutFile $promptZip -UserAgent "SecretRingsRecomp-package"
    if ((Get-FileHash $promptZip -Algorithm MD5).Hash.ToLower() -ne $promptMd5) { throw "button prompt pack: MD5 mismatch" }
}
$promptDir = Join-Path $dist "textures\RSR"
if (Test-Path $promptDir) { Remove-Item -Recurse -Force $promptDir }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($promptZip)
$n = 0
try {
    foreach ($e in $zip.Entries) {
        $name = $e.FullName -replace '\\', '/'
        if (-not $name.StartsWith("RSRE8P/A - ") -or $name.EndsWith("/")) { continue }
        $dst = Join-Path $promptDir ($name.Substring("RSRE8P/".Length) -replace '/', '\')
        New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
        [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dst, $true)
        $n++
    }
} finally { $zip.Dispose() }
if ($n -eq 0) { throw "button prompt pack: no textures found" }
@"
Xbox button prompts for Sonic and the Secret Rings, unmodified, from:

  "HD Xbox One/Series (And PS4/5) GUI and Controls" by Accelerate
  https://gamebanana.com/mods/390496
  Licence: Creative Commons Attribution-NonCommercial-NoDerivs 4.0
  (https://creativecommons.org/licenses/by-nc-nd/4.0/)

Credits listed by the mod: Accelerate (modder); SEGA/Sonic Team (the game and the Sonic
Unleashed button prompts); upscaled with Zyro (Hostinger).

Not part of SecretRingsRecomp's GPL-2.0 licence. Delete this folder for the original Wii
prompts, or turn off "HD texture packs" in the settings.
"@ | Set-Content (Join-Path $promptDir "CREDITS.txt")
"button prompts: $n textures"
@"
You don't need to put anything here. Start SecretRingsRecomp.exe and select your own disc
image (USA, Europe or Japan; ISO, RVZ, WIA or WBFS) in the file dialog, wherever it is on your PC.
The launcher installs the game data into this folder; the image is not needed afterwards.

Optional, if you have one:
  textures\RSR\... or textures\<game ID>\...    (Dolphin-format HD texture pack)
"@ | Set-Content (Join-Path $dist "game\ABOUT_THIS_FOLDER.txt")
"packaged to $dist"
