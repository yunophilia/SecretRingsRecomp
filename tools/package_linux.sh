#!/bin/bash
# Packs a Linux build into dist/SecretRingsRecomp-<version>-linux-x86_64.AppImage (no game data).
#   tools/package_linux.sh [-b build dir] [-c shader cache dir] [-v version]
# In two steps (the release workflow builds Linux and Windows on different machines):
#   tools/package_linux.sh -S                      collect dist/AppDir from the build only
#   tools/package_linux.sh -A dist/AppDir -c DIR   add the shader cache and make the AppImage
# The shader cache to ship is normally the one the Windows package made (DXBC from
# Microsoft's compiler, which DXVK uses the same way on both); without -c the keys in
# data/shadercache are compiled here with vkd3d-shader. The game writes its data (installed
# game files, saves, config.ini, new shaders) to $XDG_DATA_HOME/SecretRingsRecomp, as an
# AppImage is read-only.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
build=$root/build/linux-clang cache="" version="${SRR_VERSION:-}" stageOnly=0 appdir=""
while getopts "b:c:v:SA:" o; do
    case $o in b) build=$OPTARG ;; c) cache=$OPTARG ;; v) version=$OPTARG ;; S) stageOnly=1 ;; A) appdir=$OPTARG ;; *) exit 2 ;; esac
done
[ -n "$version" ] || version=$(git -C "$root" describe --tags --always --dirty 2>/dev/null || echo dev)

stage() {   # stage <AppDir>: everything except the shader cache
    local appdir=$1 out=$root/out
    local exe=$out/SecretRingsRecomp bin=$1/usr/bin lic=$1/usr/share/licenses/SecretRingsRecomp
    [ -x "$exe" ] || { echo "build first (cmake --build --preset linux-clang)"; exit 1; }
    rm -rf "$appdir"
    mkdir -p "$bin/shadercache" "$lic" "$appdir/usr/share/applications" "$appdir/usr/share/icons/hicolor/scalable/apps"
    cp "$exe" "$bin/"
    strip --strip-debug "$bin/SecretRingsRecomp"
    cp -L "$out/libSDL3.so.0" "$out/libdxvk_d3d11.so.0" "$out/libdxvk_dxgi.so.0" "$bin/"
    printf '#!/bin/sh\nhere=$(dirname "$(readlink -f "$0")")\nexec "$here/usr/bin/SecretRingsRecomp" "$@"\n' > "$appdir/AppRun"
    cp "$root/data/linux/secretringsrecomp.desktop" "$root/data/linux/secretringsrecomp.svg" "$appdir/"
    cp "$root/data/linux/secretringsrecomp.desktop" "$appdir/usr/share/applications/"
    cp "$root/data/linux/secretringsrecomp.svg" "$appdir/usr/share/icons/hicolor/scalable/apps/"
    # licences: the game (GPL-2.0) and the libraries inside the AppImage
    cp "$root/LICENSE" "$lic/LICENSE"
    cp "$root/README.md" "$lic/README.md"
    cp "$build/_deps/sdl3-src/LICENSE.txt" "$lic/SDL3.txt"
    cp "$build/_deps/imgui-src/LICENSE.txt" "$lic/imgui.txt"
    cp "$build/vkd3d_build-prefix/src/vkd3d_build/LICENSE" "$lic/vkd3d-shader.txt"
    cp "$root/data/linux/licenses/dxvk.txt" "$lic/dxvk.txt"
    cp "$root/data/linux/licenses/nod.txt" "$lic/nod.txt"
    prompts "$bin/textures/RSR"
}

# prompts <dir>: the Xbox button prompts of "HD Xbox One/Series (And PS4/5) GUI and
# Controls" by Accelerate (gamebanana.com/mods/390496, CC BY-NC-ND 4.0), unmodified, as
# tools/package.ps1 does for Windows: the mod's zip pinned by file id and MD5
prompts() {
    local dst=$1 zip=$root/out/gb390496_1756030.zip md5=bc53140d85890cda227705c313eb3628
    if [ ! -f "$zip" ] || [ "$(md5sum < "$zip" | cut -d' ' -f1)" != $md5 ]; then
        curl -fsSL -A SecretRingsRecomp-package -o "$zip.part" https://gamebanana.com/dl/1756030
        [ "$(md5sum < "$zip.part" | cut -d' ' -f1)" = $md5 ] || { echo "button prompt pack: MD5 mismatch"; exit 1; }
        mv "$zip.part" "$zip"
    fi
    rm -rf "$dst"
    python3 - "$zip" "$dst" <<'PY'
import os, sys, zipfile
z, dst, n = zipfile.ZipFile(sys.argv[1]), sys.argv[2], 0
for i in z.infolist():
    name = i.filename.replace('\\', '/')
    if not name.startswith('RSRE8P/A - ') or name.endswith('/'):
        continue
    out = os.path.join(dst, *name.split('/')[1:])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'wb') as f:
        f.write(z.read(i))
    n += 1
if not n:
    sys.exit('button prompt pack: no textures found')
print('button prompts:', n, 'textures')
PY
    cat > "$dst/CREDITS.txt" <<'TXT'
Xbox button prompts for Sonic and the Secret Rings, unmodified, from:

  "HD Xbox One/Series (And PS4/5) GUI and Controls" by Accelerate
  https://gamebanana.com/mods/390496
  Licence: Creative Commons Attribution-NonCommercial-NoDerivs 4.0
  (https://creativecommons.org/licenses/by-nc-nd/4.0/)

Credits listed by the mod: Accelerate (modder); SEGA/Sonic Team (the game and the Sonic
Unleashed button prompts); upscaled with Zyro (Hostinger).

Not part of SecretRingsRecomp's GPL-2.0 licence. Turn off "HD texture packs" in the
settings for the original Wii prompts.
TXT
}

if [ -z "$appdir" ]; then
    appdir=$root/dist/AppDir
    stage "$appdir"
    [ $stageOnly = 1 ] && { echo "staged $appdir"; exit 0; }
fi
bin=$appdir/usr/bin
chmod +x "$appdir/AppRun" "$bin/SecretRingsRecomp"   # artifacts lose the exec bit

# shader cache
if [ -n "$cache" ]; then
    cp "$cache"/*.cso "$cache"/*_keys.bin "$bin/shadercache/"
else
    cp "$root"/data/shadercache/*_keys.bin "$bin/shadercache/"
    "$bin/SecretRingsRecomp" --precompile-shaders "$bin/shadercache"
fi

# appimagetool and its runtime, pinned (https://github.com/AppImage)
tools=$build/appimage-tools
mkdir -p "$tools"
fetch() {   # fetch <url> <sha256> <file>
    if [ ! -f "$3" ] || ! echo "$2  $3" | sha256sum -c --quiet - 2>/dev/null; then
        curl -fsSL -o "$3.part" "$1"
        echo "$2  $3.part" | sha256sum -c --quiet -
        mv "$3.part" "$3"
    fi
}
fetch https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage \
      ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0 "$tools/appimagetool"
fetch https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64 \
      2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d "$tools/runtime-x86_64"
chmod +x "$tools/appimagetool"

mkdir -p "$root/dist"
target=$root/dist/SecretRingsRecomp-$version-linux-x86_64.AppImage
rm -f "$target"
# extract-and-run: works without FUSE (CI containers)
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$tools/appimagetool" --no-appstream --runtime-file "$tools/runtime-x86_64" "$appdir" "$target"
echo "packaged to $target"
