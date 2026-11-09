# TAS scripts (test automation)

Scripted runs drive player 1 with controller input timed by the guest clock and read
game state for telemetry. They never change game code or game data: input goes through
the normal controller path and telemetry only reads guest memory. The one exception is
`poke`, which only `clear1.tas` uses to prepare a test save. While a script runs,
real controllers are ignored, rumble is off and the keyboard is only read when the
window has focus.

## Running

```
powershell -ExecutionPolicy Bypass -File tools/tas_run.ps1 -Script tools/tas/speed.tas [-Fps60] [-Full] [-Scale N]
powershell -ExecutionPolicy Bypass -File tools/tas_batch.ps1 [-Filter speed] [-Rates 30,60]
```

`tas_run.ps1` copies `out/tasnand/<Save>` (default `base`, an empty NAND, so every run
starts from a fresh save) to a run folder (the player's own `nand/` is never used),
starts the game minimized and collects `out/tas/<tag>.log`, `<tag>.csv` and screenshots in
`out/tas/shots/<tag>/`. Runs are low impact by default: muted, 1x internal resolution,
below-normal priority (`-Full` uses the real settings). Game options for scripted runs:
`--tas <script> --telemetry <csv> --nand <dir> --mute --scale <n>`.

## Scripts (tools/tas)

| script | what it does |
|---|---|
| `boot_stage1.tas` | shared prefix: fresh save, title, Adventure, new file, Lost Prologue paragraph 1, skips the story scene |
| `speed.tas` | running speed, jump height and air time (compare the `_30` and `_60` CSVs) |
| `controls.tas` | brake, tilt back, jump + thrust, plain jump |
| `tilt.tas` | brake, then backtracking (remote upside down) and forward tilt |
| `home_pause.tas` | HOME menu and pause menu during gameplay, with screenshots |
| `party.tas` | main menu, Party mode setup, character select and the party board |
| `party_tournament.tas` | Party mode, 1 player + 3 computer players: Tournament Palace, six minigames with screenshots (the games are random; use `-Seconds 900`) |
| `party_4p.tas` | the same with 4 players (four Wii Remotes) |
| `party_2p.tas` | the same with 2 players (two Wii Remotes) + 2 computer players; player 2 picks a character and plays its matches |
| `clear1.tas` | fresh save: clears Lost Prologue, Paragraph 01 (ring count poked to 49) and saves; the start of a test save |
| `sand_oasis_<type>.tas` | `allworlds` save: a Sand Oasis mission of each type (head to head, no pearls, beat the clock, collect rings, rampage, chain of rings, boss), 50 s of play |
| `boss_<world>.tas` | `allworlds` save: the world's boss (Evil Foundry, Pirate Storm, Night Palace's Boss Duel) or, without one, the last mission in its list; 50 s |
| `last_chapter.tas` | `allworlds` save: Night Palace's Last Chapter, 150 s |
| `world_<name>.tas` | `allworlds` save: a world's first mission, 45 s of play with screenshots (compare `-Fps60` with 30) |
| `find_player.tas`, `find_jump.tas` | memory dumps while steering / jumping; `find_pos.py` searches them for moving float vectors |

## Script language

One command per line, `#` starts a comment. Commands run in order; input commands take
guest time.

| command | effect |
|---|---|
| `players N` | controllers the game sees (1 to 4); players 2-4 take the `P2:` ... `P4:` inputs |
| `filemark` | `file` conditions only count disc reads after this point (default: script start) |
| `wait S` | no input for S seconds |
| `hold S INPUT` | hold INPUT for S seconds |
| `tap INPUT [S]` | hold for S (default 0.1) then release for 0.1 s |
| `mash INPUT S [P]` | press repeatedly for S seconds, period P (default 0.2) |
| `set INPUT` / `set` | background input added to everything that follows / clear it |
| `until COND [and COND] [mash INPUT[,INPUT...] [period P]] [timeout S] [soft]` | wait until all conditions hold, pressing INPUT every P s (default 0.2) meanwhile; several comma-separated inputs are pressed in turn (default timeout 60 s; a timeout fails the run with exit code 3, or with `soft` goes on to the next command) |
| `check COND [msg TEXT]` | log PASS/FAIL without waiting |
| `poke TYPE EXPR VALUE` | write guest memory; changes game state, only for preparing test saves |
| `repeat N` ... `end` | loop |
| `log TEXT` | log line and telemetry marker |
| `shot NAME` | screenshot to `out/shots/NAME.bmp` |
| `dump NAME` | MEM1/MEM2 to `out/dumps/NAME.mem1/.mem2` |
| `calls NAME` / `calls -` | write call counts since the last `calls` to `out/dumps/NAME.calls` / reset (call-counting build only) |
| `watch NAME TYPE EXPR` | telemetry column (sampled once per presented frame) |
| `include FILE` | include another script (relative path) |
| `quit [CODE]` | exit the game |

INPUT: `A B X Y LB RB START BACK UP DOWN LEFT RIGHT HOME LS RS` joined with `+`, and
analog values `LX= LY= RX= RY= LT= RT=` (-1..1) and pointer `PX= PY=` (0..1 of the
screen), e.g. `hold 2 LY=1.0+A`. A word prefixed `P2:`, `P3:` or `P4:` is that player's input (the prefix covers the
whole word), e.g. `tap A P2:A P3:RIGHT+A`. Buttons use this port's logical layout: A = Wii 2 (jump), X = thrust
(homing attack), B = Wii 1 (brake), RB/LB = Wii A/B, START = +, HOME; `LX` steers and
`LY=-1` turns the remote upside down (backtrack).

COND: `file TEXT` (a disc file whose path contains TEXT was read since the last
`filemark`) or `TYPE EXPR OP VALUE` with TYPE `u8 s8 u16 s16 u32 s32 f32` and OP
`== != < <= > >=`.

EXPR: hex address, probe `p0`..`p15`, `+`/`-` offsets and `[expr]` to read a pointer,
e.g. `[80803e10]+2050`. Unmapped addresses read as missing values.

## Test saves

`-Save <name>` starts a run from `out/tasnand/<name>`. To get a save with every world
unlocked (`allworlds`, used by the `world_*.tas` scripts):

```
powershell -ExecutionPolicy Bypass -File tools/tas_run.ps1 -Script tools/tas/clear1.tas
cp -r out/tasnand/run_clear1_30 out/tasnand/allworlds
python tools/make_test_save.py out/tasnand/allworlds
```

`make_test_save.py` describes the save file format (checksum, world unlock flags,
mission records).

## Known addresses (USA/Japan build: RSRE8P, RSRJ8P)

| what | expression |
|---|---|
| Sonic height above ground | `f32 9102cd4c` (Lost Prologue, after `boot_stage1.tas`) |
| distance along the path | `f32 9102cd50` (decreases while running forward) |
| lateral offset | `f32 9102cd54` (left negative) |
| KPAD channel 0 state | `80692b60` (stride 2104) |
| ring count | one of `u32 9102d378`, `9102d37c`, `9102e0e0`, `91efc544`, `91efcdf8` (Lost Prologue, Paragraph 01; `clear1.tas` sets all five) |

The heap addresses hold for the fresh-save boot path above; other routes may differ.
The European build (RSRP8P) has its static data 0x40 bytes lower (KPAD channel 0 at
`80692b20`).
