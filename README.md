# SecretRingsRecomp

A static recompilation of **Sonic and the Secret Rings** (Wii: USA `RSRE8P`, Europe
`RSRP8P`, Japan `RSRJ8P`) to native Windows x64. It is a sister project of
[BlackKnightRecomp](https://github.com/yunophilia/BlackKnightRecomp): the recompiler and
most of the runtime are shared, retargeted to this game's executable and its older
(2006/2007) Wii SDK. The goal: play it natively on PC with a normal controller instead of
a sideways-held Wii Remote.

**You must own the game.** Nothing from the game is in this repository; the build reads your
own disc image.

## How it works

```
main.dol ──► tools/analyze.py ──► tools/recomp.py ──► generated/*.cpp ─┐
 (PowerPC)    function discovery    PPC → C++ codegen   (21.7k functions)├─► SecretRingsRecomp.exe
                                                        runtime/ ────────┘
```

* **Recompiler** (`tools/`): decodes every Gekko/Broadway instruction (incl. paired singles
  and quantized loads/stores) and emits one C++ function per guest function. Guest RAM is a
  4 GiB host reservation with MEM1/MEM2 mirrored at their cached/uncached addresses, so
  guest pointers map directly to host memory. Function names come from the disc's
  `SONICRINGS.sel` symbol table and Dolphin's signature database.
* **CPU runtime** (`runtime/cpu`): SPRs, time base / decrementer, exact `fres`/`frsqrte`
  tables, indirect call dispatch.
* **OS** (`runtime/kernel`): the game's *own* Revolution OS runs recompiled. Every guest
  thread is a host fiber (`OSSaveContext`/`OSLoadContext` become fiber switches) and
  external / decrementer exceptions are delivered at safe points.
* **Hardware** (`runtime/hw`): VI (timing derived from the VI clock and line width, so
  480p runs at 60 Hz), PI, CP/PE, DSP/AI, EXI, SI and the Hollywood IPC registers.
* **IOS** (`runtime/ios`): high-level `/dev/di`, `/dev/fs` (NAND in `nand/` next to the exe;
  saves land in `nand/title/00010000/52535245/data`), `/dev/es`, `/dev/stm`.
* **Graphics** (`runtime/gx`): the GX FIFO is decoded and rendered with Direct3D 11 on its own
  thread, with per-state generated shaders (TEV, lighting, texgen, indirect texturing, fog),
  EFB copies as render-to-texture, 3x internal resolution by default, a disk shader cache and
  Dolphin-format HD texture packs.
* **Input** (`runtime/input`): the WPAD library is replaced at the API level; KPAD runs
  recompiled on top of it. This SDK's KPAD reads a ring buffer that WPAD fills on every
  report (`WPADSetAutoSamplingBuf`), so the HLE writes synthesised sideways-Wii-Remote
  samples there: the left stick rolls the remote to steer, thrusts become acceleration
  pulses, and "tilt back" turns the remote upside down (what the game checks for
  backtracking).
* **Audio** (`runtime/audio`): the AX DSP microcode is replaced by a port of Dolphin's AX
  HLE; output goes through XAudio2.

## Playing

Run `SecretRingsRecomp.exe`. On first run it asks for your own disc image of the game (USA
`RSRE8P`, Europe `RSRP8P` or Japan `RSRJ8P`; ISO, RVZ, WIA or WBFS). The launcher installs the game data from it into
`game/extracted/` next to the exe (about 3.5 GB); the image is not needed afterwards.

All three releases have the same game data, with the same six languages. The USA and
Japanese discs share one executable. The European disc has its own build of it: the same
code at slightly different addresses, minus a cap at 999 on one counter that the USA build
has. Both builds are recompiled together and share one copy of the code: where they
differ only in an address, the code picks the value for the running release. The emulated Wii matches
the disc: an NTSC console for USA and Japan, and a PAL console with EuRGB60 (60 Hz) for
Europe. Each release keeps its own saves (`nand/title/00010000/<title ID>/data`), as on a
real Wii.

### Steam Deck and Linux (Proton)

There is no native Linux build; the Windows build is meant to run through Proton. The
renderer has the fixes BlackKnightRecomp (the same runtime) needed there: its generated
shaders avoid `isnan()`, which Wine's HLSL compiler lacks (a black screen with audio
playing), shaders Proton 10 compiles itself get their colours fixed, and releases include
precompiled shaders in `shadercache/`, so keep that folder next to the exe. **Not tested
under Proton with this game yet**; reports are welcome.

1. Unzip the release somewhere in your home folder and start it once from Desktop Mode or
   your desktop: the launcher installs the game data from your disc image.
2. In Steam: *Games > Add a Non-Steam Game to My Library*, browse to
   `SecretRingsRecomp.exe` (file type filter "All files").
3. In the shortcut's *Properties > Compatibility*, tick *Force the use of a specific Steam
   Play compatibility tool* and pick Proton Experimental, 10.0 or 9.0.

A Steam Deck acts as an Xbox controller, so the table below applies. If the screen stays
black, `SecretRingsRecomp.log` next to the exe says why (it logs "running under Wine", the
HLSL compiler in use, and any shader or D3D error); please attach it to an issue.

## Controls (default)

Based on the [Xbox controls mod for Dolphin](https://gamebanana.com/mods/390496) by
default, including its choice to turn off auto-run: Sonic runs while the left stick is
pushed and stops when you let go. Turn on *Auto-run* in the settings (`auto_run = true`)
to play as on the Wii, where he runs on his own and B brakes.

| Controller | Keyboard | Wii Remote (sideways) | Action |
|---|---|---|---|
| Left stick | W / A / S / D | tilt (and 1 released) | Run (push any way), steer (left/right) |
| Left stick down (past half) | S | turn upside down | Backtrack |
| Right stick left/right, LB / RB | | tilt left/right | Steer |
| Right stick down | J / left click | thrust forward | Homing attack / air dash |
| Right stick up | | turn upside down | Backtrack |
| A | Space | 2 | Jump |
| B | K | 1 | Run straight (auto-run off) / brake (auto-run on) |
| X, or LT + RT | L | shake | Shake |
| Start | Enter | + and A | Pause / confirm |
| D-pad | Arrow keys | D-pad (turned a quarter) | Menus |
| View (Back) | F1 | | Settings overlay |
| View + Start | H | HOME | HOME menu |

With auto-run off, the game sees button 1 (brake) held whenever the left stick is centred
and B is not held, exactly as the mod's Wii Remote profile does.

Bindings, the steering tilt range and steering inversion can be changed in the settings
(launcher or in game) or in `config.ini`. F11 or Alt+Enter toggles fullscreen.

## Building

Requirements: Windows 10+, Visual Studio 2022 or newer (Build Tools are enough) with the C++
workload and the "C++ Clang Compiler for Windows" component, CMake 3.21+ and Ninja (both ship
with Visual Studio), Python 3.10+ (with numpy and Pillow for the test tools), and an internet
connection for the first configure (it downloads [nod](https://github.com/encounter/nod) and
Dear ImGui). `tools/dev_build.bat` sets up the Visual Studio environment and builds.

1. Configure and build the installer: `tools\dev_build.bat`
2. Install the game data: `out\srr_install path\to\image` (any of the three releases)
3. Extract the build inputs of the releases you did not install into `game/inputs/`:
   `out\srr_install --build-inputs path\to\other-image`. The USA or Japanese main.dol is
   required. Without the European one, the exe runs only the USA and Japanese releases.
4. Generate the recompiled sources: `python tools/build_generated.py` (`generated/`, plus
   `generated/eu/` for the European build). To rematch SDK names, pass
   `--dsy <Dolphin>/Sys/totaldb.dsy` with `--reanalyze`.
5. Optional, recommended: recompile the `hbm_part.rso` module (movies and the HOME menu;
   otherwise they run in the interpreter, too slowly for movies at 60 fps). Run the game
   once with `SRR_DUMPMEM=1` set until the title screen; it writes `mem1_dump.bin` next
   to the exe. Move it to `out/`, run `python tools/rso.py`, then step 4 again. For the
   European release, run it with that release's data, put the dump in `out/eu/` and run
   `python tools/rso.py out/eu/mem1_dump.bin --out out/eu`.
6. Build the game: `tools\dev_build.bat` → `out\SecretRingsRecomp.exe`

## Settings

`config.ini` next to the executable (also editable in the launcher and the in-game
overlay): `frame_rate` (30 original, or 60: game logic is delta-timed, so speeds and jumps
measure the same), `internal_scale`, window/fullscreen/vsync, anisotropy, texture packs
(`textures/RSR/...` for every release, or `textures/<game ID>/...`), language, rumble, Wii Remote speaker, `tilt_range`, `tilt_sign`
and the button/keyboard bindings.

## Testing

* `tools/run_test.ps1 -Seconds N -GameArgs "--nobox --skip-launcher --input-script <file> --shots N"`
  runs a timed input script and saves screenshots; `python tools/contact.py` makes a
  contact sheet of them.
* `tools/tas_run.ps1 -Script tools/tas/<x>.tas [-Fps60]` runs TAS scripts with telemetry
  (docs/tas.md). `tools/tas/speed.tas` measures Sonic's speed and jump at 30 vs 60 fps,
  `controls.tas` / `tilt.tas` check brake, backtracking and air thrusts.
* `python tools/gen_soak.py out/soak.txt` generates a random-input soak script.

## Status

Playable: boot, menus, story scenes, FMV, saves and gameplay with a controller (steering,
jump, homing attack, brake, backtracking) at 30 or 60 fps. See `docs/progress.md`.

## License

GPL-2.0-only, like BlackKnightRecomp (see [LICENSE](LICENSE)). Parts of the runtime are
ported from or closely follow the [Dolphin emulator](https://github.com/dolphin-emu/dolphin)
(GPL-2.0-or-later). No game code or data is included; you need your own copy of the game.
