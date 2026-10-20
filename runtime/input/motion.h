#pragma once
#include <cstdint>

// Synthesises sideways-held Wii Remote samples from the host gamepad.
void Motion_Step(int chan, float dt);
// Writes one WPADStatus (size bytes: 42 core, 50 with an extension, ...) at guestStatus
void Motion_FillStatus(int chan, uint32_t guestStatus, uint32_t size, bool connected);
int Motion_GravityUnit(uint32_t type);
