# Progress log

## Milestones

- [x] Fork of BlackKnightRecomp's recompiler and runtime, renamed and retargeted to RSRE8P
      (installer game ID + main.dol SHA-1, file manifest, NAND title ID 52535245)
- [x] Function analysis: 21,726 functions, 327 jump tables; SDK names from
      `SONICRINGS.sel` and Dolphin's signature DB (2,618 matches)
- [x] Runtime overrides remapped to this executable (OS context switch, interrupts,
      OSReport/OSPanic/OSFatal, VIGetRetraceCount, WPAD) with `tools/fuzzymatch.py`
- [x] Boot: OS, IOS, DVD, SC, NAND, DSP/AX, KPAD, the hbm_part.rso module
- [x] Title screen, menus, file select, story scenes, FMV
- [x] Gameplay (Lost Prologue): steering, jump, homing attack/air thrust, brake, backtracking
- [x] Emulated console is a US (NTSC) Wii, as RSRE8P is the USA release; earlier builds
      described a European console
- [x] 480p at 60 Hz: VI timing from HLW and the VI clock (the old half-line heuristic
      ran 480p modes at 50 Hz)
- [x] 60 fps option (`frame_rate = 60`): speed 198.6 vs 198.4 units/s, jump 11.73 vs 11.75,
      air time 0.53 s at both rates (tools/tas/speed.tas)
- [x] Settings: steering tilt range and inversion
- [x] European (RSRP8P) and Japanese (RSRJ8P) releases: the Japanese main.dol is the USA
      one; the European build is recompiled together with it, sharing the code of all
      but 4 functions, and picked at startup from the installed disc; the console region,
      title ID / save folder and file manifest follow the release
- [x] Party mode with 2 players (two Wii Remotes) at 30 and 60 fps: each player picks
      their character and a computer player's, starts and plays their own matches
      (Marksman with both players against each other); 10 more minigames, no errors
- [x] Party mode with 4 players (four Wii Remotes) at 30 and 60 fps: each picks a
      character, the tournament plays its matches (Color Balloon, Bubble Hunt and Carpet
      among them), no errors; 60 fps dips only for a moment at minigame ends (loading)
- [ ] The Wii Remote speaker: the game streams each remote's mix all the time
      (fn_801C40A8: AXRmt samples -> WENCGetEncodeData -> WPADSendStreamData) and the
      HLE decodes and plays it, but in ~1 h of gameplay and Party mode (Treasure Box
      included) the mix was silent: the game routes only some sound effects to a
      remote (its sound engine calls AXSetVoiceRmtOn, 0x80544034, for sounds with
      remote flags, from 0x80306ae4), and none played. The voice layout is right (the
      AXSetVoice* setters write the same offsets the AX HLE reads). Still to find: a
      scene that plays one
- [x] 60 fps in every world: the first mission of all seven worlds after Lost Prologue
      holds 59-60 fps with the same progress as at 30 fps at the same time
      (`tools/tas/world_*.tas` on a save from `tools/make_test_save.py`)
- [x] Party mode, 1 player + 3 computer players at 30 and 60 fps: Tournament Palace
      with 12 different minigames (Pirate Flag, Edge Race, Heavy Ball, Parasol Diving,
      Marksman, Balance Battle, Canoe Salvage, Treasure Box, Kri Ma Djinn, Steel
      Survival, Cogwheel Relay, Canoe Survival); timers run at real time at both rates
- [x] 60 fps in each mission type (Sand Oasis: Head to Head against Uhu, No Pearls,
      Beat the Clock, Collect Rings, Rampage, Chain of Rings, the Sand Scorpion boss):
      the same progress as at 30 fps, the Beat the Clock timer counts 5 s per 5 s at
      both rates, 59-60 fps
- [x] 60 fps soak: 15 min of random input in Sand Oasis (missions, retries, pause) on the
      `allworlds` save, 59.3-60.3 fps throughout, no errors
- [x] 60 fps: every boss in the mission lists (Sand Scorpion, Ifrit Golem, Captain
      Bemoth, Erazor Djinn's Boss Duel) and Night Palace's Last Chapter (2.5 min of
      story, the same subtitle at the same moment at both rates) match the 30 fps runs.
      Dinosaur Jungle, Levitated Ruin and Skeleton Dome list no boss.
- [x] 60 fps: a playthrough from a new file to the ending (`tools/story_run.py`, docs/tas.md):
      80 runs, 52 missions cleared in all eight worlds, with the story movies in between
      (the first ones played through, e.g. e0002 at 59.6-60.3 fps for 3 min; later ones
      skipped with +), the unlock dialogs, saves, Erazor Djinn's Boss Duel, the last movie
      (e0028) and the staff roll, back to the title screen. After boot: 5,126 one-second
      samples, minimum 58.3 fps, median 59.9; no errors. Missions were made "collect 1
      ring" in a test copy of the data so a script can clear them; Captain Bemoth (no
      rings in the arena) was marked cleared in the save and Skeleton Dome unlocked by
      hand. One spot in Sand Oasis (Sonic stuck on a leaning pillar when not steering)
      happens the same at 30 fps
- [ ] Verify the bloom/glow pass against real hardware or Dolphin (dark halos behind the
      crystal blocks in Lost Prologue come from a subtractive blend the game really uses)
- [x] Recompile the `hbm_part.rso` module (USA/Japan). It holds the movie player as well
      as the HOME menu: interpreted, a movie frame took ~21 ms of CPU, so movies ran at
      ~47 fps at 60; recompiled they hold 60. `tools/rso.py` takes a memory dump
      (`SRR_DUMPMEM=1`, or the TAS `dump` command) to find the linked module
- [x] The European build's copy of the module (linked 0x40 lower): matched with the
      USA one like main.dol, all 1,657 functions shared; boot movies hold 60 fps on both

## Releases

| | USA | Europe | Japan |
|---|---|---|---|
| game ID / title | RSRE8P / 52535245 | RSRP8P / 52535250 | RSRJ8P / 5253524A |
| main.dol SHA-1 | c4d611da… | 9ffb9cf2… | c4d611da… (same as USA) |
| console | NTSC, US | PAL + EuRGB60, UK | NTSC, Japan |

Files in `files/` are identical in all three apart from the `.sel` symbol maps. The
European main.dol differs from the USA one in a single function (0x803E53A0 in the USA
build caps a halfword counter at 999; the European build has no cap and is 0x34 bytes
shorter). Code after it is 0x34 bytes lower, data 0x40 lower (r13 0x8069CC00, r2
0x806A1520). `tools/regions.py` matches the two builds' functions (21,724 of 21,726
identical apart from relocated addresses). `tools/recomp.py --eu` generates each matched
pair once, named by the USA address: statements that differ only in a value (data and
return addresses, callees, the jump-table base) read `PPC_SEL(usa, eu)`, which picks by
`g_ppcEuCode` (cached in a local per function). 21,722 functions are shared; the
European build has 4 of its own (`generated/eu/`: the counter function, a data table
analysed as code, one function where an offset is 0 in one build and not the other, and
one whose jump table jumps into other functions, which can't be a selected `case`),
reached through its own dispatch table. The exe is 48 MB (88 MB with two copies, 46 MB
without the European code). The runtime's overrides and patches
therefore apply to both. Runtime data addresses that differ by build are picked by
`g_ppcEuCode` (`threads.cpp`).

## Porting notes (RSRE8P)

* r13 = 0x8069CC40, r2 = 0x806A1560. Exception handler table pointer at r13-15432
  (0x80698FF8), the table itself at 0x80003000.
* SEL section n is the DOL's text section n-1 (`tools/analyze.py` reads the bases from the DOL).
* Frame pacing: retraces per frame = 60 / `[cfg+12]`; the initial 30 is `li r0,30` at
  0x800B6878 (patched to the configured rate in `tools/recomp.py`).
* Video mode: progressive scan (SC item 9 = IPL.PGS) with a component cable picks
  NTSC 480p (`GXRenderModeObj` at 0x805EEF8C; on a PAL console it would pick EURGB60
  480p at 0x805EF07C, or PAL 50 Hz at 0x805EF004 without progressive scan).
  This SC library reads items by ID
  through a name table at 0x805B5058 (0 CB, 1 AR, 2 ARN, 3 DH, 4 E60, 5 IDL, 6 LNG, 7 NIK,
  8 PC, 9 PGS, ...).

## Wii Remote (2006 WPAD/KPAD)

* No WPADSetSamplingCallback. KPAD (0x80558C3C reset, 0x80558E4C KPADRead) gives WPAD a
  32-entry ring buffer with `WPADSetAutoSamplingBuf` (0x802B2814) and reads
  `WPADGetLatestIndexInBuf` (0x802B2990). Entry size depends on the data format
  (42 core, 50 Nunchuk, 54 Classic, 90 other); byte 41 is the error code.
* KPAD keeps re-sending the DPD (IR camera) command, and re-arming the buffer, until
  `WPADIsDpdEnabled` matches the state it wants, so the HLE tracks `WPADControlDpd`.
  The game turns DPD off (it does not use the pointer).
* WPAD control blocks: pointer table at 0x8063AD30 (+2028 buffer, +2032 latest index,
  +2036 length, +2040 data format). KPAD per-channel state at 0x80692B60, stride 2104.
* The game's pad conversion (0x800B52DC) keeps the tilt vector (-acc.x, -acc.z, acc.y)
  of KPAD's acceleration, averaged over the frame's samples (0x800B4954), and detects
  thrusts/shakes from per-axis jerk above 0.6 (0x800B50D8).
* Steering responds to roll (gravity between the remote's Z and Y axes). Backtracking only
  happens with the remote upside down (gravity on -Z): ~105° of tilt does nothing,
  175° moves Sonic backwards at 60 units/s.

## Test telemetry (fresh save, Lost Prologue paragraph 1)

Sonic's path-relative state is at 0x9102CD4C (height above ground), 0x9102CD50 (distance
along the path, decreasing while running forward) and 0x9102CD54 (lateral offset, left
negative). The heap address is stable for the boot path in `tools/tas/boot_stage1.tas`.
