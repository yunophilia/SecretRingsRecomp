#pragma once
// The release being run (USA, Europe or Japan), from the installed game data.
#include "install/releases.h"

#include <string>

// The running release; USA until Region_Select
extern const Release* g_release;

// This executable includes the release's recompiled code (Europe's code set is optional
// at build time, see tools/build_generated.py)
bool Release_Runnable(const Release& r);

// Picks the release of the game data in dataDir. False (with a message) if it is not
// one this executable can run.
bool Region_Select(const std::string& dataDir, std::string& error);
