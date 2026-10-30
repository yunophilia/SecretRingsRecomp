#pragma once
#include <cstdint>
#include <cstring>
#include <string_view>

// The releases of the game this project runs. USA and Japan ship the same main.dol;
// Europe's is a separate build, recompiled as its own code set (tools/regions.py).
struct Release
{
    const char* gameId;       // disc game ID
    const char* name;         // shown to the user
    uint32_t titleLo;         // low half of the title ID (save data in /title/00010000/<titleLo>)
    bool pal;                 // European console (PAL, EuRGB60)
    bool euCode;              // runs the European code set
    uint8_t dolSha1[20];      // main.dol the code was recompiled from
    uint32_t mask;            // bit in the file manifest (releases_files.inc)
};

inline constexpr Release kReleases[] = {
    { "RSRE8P", "USA", 0x52535245, false, false,
      { 0xc4, 0xd6, 0x11, 0xda, 0x44, 0xcf, 0x89, 0xa6, 0xbc, 0x76, 0xc2, 0xec, 0x86, 0xc2, 0x44, 0x9e, 0xe2, 0x9a, 0xbc, 0xdb }, 1 },
    { "RSRP8P", "Europe", 0x52535250, true, true,
      { 0x9f, 0xfb, 0x9c, 0xf2, 0x82, 0xf6, 0xff, 0x41, 0x6f, 0x99, 0x51, 0x04, 0x02, 0x1b, 0x45, 0x1d, 0xf9, 0x1c, 0xe5, 0x22 }, 2 },
    { "RSRJ8P", "Japan", 0x5253524A, false, false,
      { 0xc4, 0xd6, 0x11, 0xda, 0x44, 0xcf, 0x89, 0xa6, 0xbc, 0x76, 0xc2, 0xec, 0x86, 0xc2, 0x44, 0x9e, 0xe2, 0x9a, 0xbc, 0xdb }, 4 },
};

inline const Release* Release_Find(std::string_view gameId)
{
    for (auto& r : kReleases)
        if (gameId == r.gameId) return &r;
    return nullptr;
}
