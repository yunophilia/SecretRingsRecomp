# Progress log

## Milestones

- [x] Fork of BlackKnightRecomp's recompiler and runtime, renamed and retargeted to RSRE8P
      (installer game ID + main.dol SHA-1, file manifest, NAND title ID 52535245)
- [x] Function analysis: 21,726 functions, 327 jump tables; SDK names from
      `SONICRINGS.sel` and Dolphin's signature DB (2,618 matches)
- [x] Runtime overrides remapped to this executable (OS context switch, interrupts,
      OSReport/OSPanic/OSFatal, VIGetRetraceCount, WPAD) with `tools/fuzzymatch.py`
- [x] Boot: OS, IOS, DVD, SC, NAND, DSP/AX, KPAD, HOME button RSO module (interpreted)
- [x] Title screen, menus, file select, story scenes, FMV
- [x] Gameplay (Lost Prologue): steering, jump, homing attack/air thrust, brake, backtracking
- [x] 480p EURGB60: VI timing from HLW and the VI clock (was running at 50 Hz)
- [x] 60 fps option (`frame_rate = 60`): speed 198.6 vs 198.4 units/s, jump 11.73 vs 11.75,
      air time 0.53 s at both rates (tools/tas_srr/speed.tas)
- [x] Settings: steering tilt range and inversion
- [ ] Party mode minigames (Wii Remote speaker, multiple remotes) — untested
- [ ] 60 fps in all worlds and Party mode (a 60 fps cheat code is known to break some)
- [ ] Verify the bloom/glow pass against real hardware or Dolphin (dark halos behind the
      crystal blocks in Lost Prologue come from a subtractive blend the game really uses)
- [ ] Recompile the HOME menu module (`hbm_part.rso`, runs in the interpreter for now)

## Porting notes (RSRE8P)

* r13 = 0x8069CC40, r2 = 0x806A1560. Exception handler table pointer at r13-15432
  (0x80698FF8), the table itself at 0x80003000.
* SEL section n is the DOL's text section n-1 (`tools/analyze.py` reads the bases from the DOL).
* Frame pacing: retraces per frame = 60 / `[cfg+12]`; the initial 30 is `li r0,30` at
  0x800B6878 (patched to the configured rate in `tools/recomp.py`).
* Video mode: progressive scan (SC item 9 = IPL.PGS) with a component cable picks
  EURGB60 480p (`GXRenderModeObj` at 0x805EF07C). This SC library reads items by ID
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
negative). The heap address is stable for the boot path in `tools/tas_srr/boot_stage1.tas`.
