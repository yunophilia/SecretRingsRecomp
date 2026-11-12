// Gamepad -> sideways Wii Remote sample synthesis.
//
// Secret Rings is played with the Wii Remote held sideways (D-pad under the left thumb,
// 1 and 2 under the right). Raw WPAD accelerometer axes (counts, G per 1 g): X across
// the face of the remote, Y along its length (towards the IR end), Z out of the
// buttons. Held sideways and flat, gravity reads (0, 0, +G).
//
//   steer (roll the remote like a steering wheel)  -> gravity moves between Z and Y
//   tilt back towards you (backtrack)               -> gravity moves between Z and X
//   thrust towards the screen (homing attack)       -> acceleration pulse along X
//   shake                                           -> fast alternating pulses
#include "motion.h"
#include "gamepad.h"
#include "../config.h"
#include "../kernel/memory.h"

#include <algorithm>
#include <cmath>
#include <windows.h>

extern void* Video_HWND();

namespace
{
constexpr int G = 100;   // counts per 1 g (matches the reported gravity unit)
constexpr float PI = 3.14159265f;

enum : uint16_t
{
    WPB_LEFT = 0x0001, WPB_RIGHT = 0x0002, WPB_DOWN = 0x0004, WPB_UP = 0x0008, WPB_PLUS = 0x0010,
    WPB_TWO = 0x0100, WPB_ONE = 0x0200, WPB_B = 0x0400, WPB_A = 0x0800, WPB_MINUS = 0x1000,
    WPB_HOME = 0x8000,
};

struct Pulse
{
    float t = -1.0f;        // time since start (s), <0 = inactive
    float dur = 0.0f;
    float ax = 0, ay = 0, az = 0;   // peak acceleration (g)
};

struct State
{
    GamepadState pad;
    GamepadState prevPad;
    Pulse remote;
    float roll = 0.0f;      // radians, + = right side of the remote down
    float pitch = 0.0f;     // radians, + = top tilted back towards the player
    float shakeT = -1.0f;   // shake in progress (s)
    float ptrX = 0.5f, ptrY = 0.5f;   // pointer position 0..1 (right stick / mouse)
    POINT lastMouse{ -1, -1 };
};

State s_state[4];

void StartPulse(Pulse& p, float ax, float ay, float az, float dur)
{
    p.t = 0.0f;
    p.dur = dur;
    p.ax = ax;
    p.ay = ay;
    p.az = az;
}

// Smooth out-and-back profile: positive lobe then a smaller negative lobe
float PulseShape(const Pulse& p)
{
    if (p.t < 0.0f || p.t > p.dur) return 0.0f;
    float u = p.t / p.dur;
    if (u < 0.6f) return std::sin(u / 0.6f * PI);
    return -0.6f * std::sin((u - 0.6f) / 0.4f * PI);
}

// Moves `cur` towards `target` at most `rate` radians per second (a real wrist does not
// snap from one angle to another; the game's tilt filters expect a continuous motion).
float Approach(float cur, float target, float rate, float dt)
{
    float d = target - cur;
    float m = rate * dt;
    return cur + std::clamp(d, -m, m);
}
}   // namespace

void Motion_Step(int chan, float dt)
{
    State& s = s_state[chan & 3];
    s.prevPad = s.pad;
    Gamepad_Poll(chan, s.pad);
    const GamepadState& p = s.pad;
    auto pressed = [&](uint16_t b) { return (p.buttons & b) && !(s.prevPad.buttons & b); };

    // Steering: the stick X axes and unbound LB / RB set the roll angle (full deflection =
    // tilt_range degrees)
    float steer = std::clamp(p.lx + p.rx + p.steerButtons, -1.0f, 1.0f) * g_config.tiltRange * (PI / 180.0f);
    s.roll = Approach(s.roll, steer, 8.0f, dt);

    // Backtrack: the game only moves Sonic backwards with the remote turned upside down
    // (tilted all the way back), so left stick down / right stick up / the tilt-back
    // binding past halfway flips it over. Pushing the left stick up tilts it forward a little.
    float back = std::max({ -p.ly, p.ry, p.lt });
    float pitchTarget = back > 0.5f ? 180.0f : back < -0.3f ? back * 45.0f : 0.0f;
    s.pitch = Approach(s.pitch, pitchTarget * (PI / 180.0f), 14.0f, dt);

    // Thrust forward (the homing attack and thrust bindings, right stick down): homing
    // attack, speed break forward motion
    bool thrust = pressed(PAD_X) || (p.rt > 0.6f && s.prevPad.rt <= 0.6f) || (p.ry < -0.6f && s.prevPad.ry >= -0.6f);
    if (thrust) StartPulse(s.remote, 3.5f, 0.0f, 0.0f, 0.15f);
    // Shake (its binding, or LT + RT together)
    if (pressed(PAD_Y) || (p.triggerShake && !s.prevPad.triggerShake)) s.shakeT = 0.0f;
    if (s.shakeT >= 0.0f)
    {
        s.shakeT += dt;
        if (s.shakeT > 0.5f) s.shakeT = -1.0f;
    }

    // Pointer: the right stick moves it; moving the mouse inside the window takes over.
    s.ptrX = std::clamp(s.ptrX + p.rx * dt * 0.9f, 0.0f, 1.0f);
    s.ptrY = std::clamp(s.ptrY - p.ry * dt * 0.9f, 0.0f, 1.0f);
    if (chan == 0)
    {
        HWND hwnd = (HWND)Video_HWND();
        POINT pt;
        RECT rc;
        if (hwnd && GetCursorPos(&pt) && (pt.x != s.lastMouse.x || pt.y != s.lastMouse.y))
        {
            s.lastMouse = pt;
            if (ScreenToClient(hwnd, &pt) && GetClientRect(hwnd, &rc) && rc.right > 0 && rc.bottom > 0 && pt.x >= 0 && pt.y >= 0 &&
                pt.x < rc.right && pt.y < rc.bottom)
            {
                s.ptrX = (float)pt.x / rc.right;
                s.ptrY = (float)pt.y / rc.bottom;
            }
        }
    }
    if (p.px >= 0) s.ptrX = p.px;
    if (p.py >= 0) s.ptrY = p.py;

    if (s.remote.t >= 0.0f) { s.remote.t += dt; if (s.remote.t > s.remote.dur) s.remote.t = -1.0f; }
}

int Motion_GravityUnit(uint32_t) { return G; }

void Motion_FillStatus(int chan, uint32_t st, uint32_t size, bool connected)
{
    State& s = s_state[chan & 3];
    const GamepadState& p = s.pad;
    memset(GuestPtr(st), 0, size);
    if (!connected)
    {
        Write8(st + 0x28, 253);
        Write8(st + 0x29, (uint8_t)-1);
        return;
    }
    uint16_t b = 0;
    if (p.buttons & PAD_A) b |= WPB_TWO;     // jump
    if (Gamepad_AutoRun())
    {
        if (p.buttons & PAD_B) b |= WPB_ONE;   // brake (Sonic runs on his own, as on the Wii)
    }
    else
    {
        // No auto-run (the GameBanana Xbox controls mod's Wii Remote profile): 1 (brake) is
        // held unless the left stick is pushed or the brake binding (then "run") is held,
        // so Sonic runs while the stick is pushed and stops when it is released.
        bool run = p.lx != 0.0f || p.ly != 0.0f || (p.buttons & PAD_B);
        if (!run) b |= WPB_ONE;
    }
    if (p.buttons & PAD_RB) b |= WPB_A;
    if (p.buttons & PAD_LB) b |= WPB_B;
    if (p.buttons & PAD_START) b |= WPB_PLUS;
    if (p.buttons & PAD_BACK) b |= WPB_MINUS;
    if (p.buttons & PAD_HOME) b |= WPB_HOME;
    if (p.buttons & PAD_LTHUMB) b |= WPB_ONE;
    if (p.buttons & PAD_RTHUMB) b |= WPB_TWO;
    // the D-pad is turned a quarter: screen up is the remote's "right"
    if (p.buttons & PAD_DPAD_UP) b |= WPB_RIGHT;
    if (p.buttons & PAD_DPAD_DOWN) b |= WPB_LEFT;
    if (p.buttons & PAD_DPAD_LEFT) b |= WPB_UP;
    if (p.buttons & PAD_DPAD_RIGHT) b |= WPB_DOWN;
    Write16(st + 0x00, b);

    // gravity: start from (0, 0, 1), pitch about Y (into X), then roll about X (into Y)
    float gx = std::sin(s.pitch);
    float gz0 = std::cos(s.pitch);
    float gy = gz0 * std::sin(s.roll) * g_config.tiltSign;
    float gz = gz0 * std::cos(s.roll);
    float k = PulseShape(s.remote);
    float ax = gx + s.remote.ax * k, ay = gy + s.remote.ay * k, az = gz + s.remote.az * k;
    if (s.shakeT >= 0.0f)
    {
        float w = std::sin(s.shakeT * 2.0f * PI * 8.0f) * 2.5f;
        ax += w;
        az += w * 0.5f;
    }
    auto cnt = [](float g) { return (uint16_t)(int16_t)std::clamp((int)std::lround(g * G), -511, 511); };
    Write16(st + 0x02, cnt(ax));
    Write16(st + 0x04, cnt(ay));
    Write16(st + 0x06, cnt(az));

    // IR: two sensor bar dots, so menus that use the pointer still work.
    float px = s.ptrX, py = s.ptrY;
    int cx = (int)(512 + (0.5f - px) * 460.0f);
    int cy = (int)(486 + (0.5f - py) * 452.0f);
    struct Dot { int x, y; } dots[2] = { { cx - 180, cy }, { cx + 180, cy } };
    for (int i = 0; i < 2; i++)
    {
        uint32_t o = st + 0x08 + i * 8;
        Write16(o + 0, (uint16_t)dots[i].x);
        Write16(o + 2, (uint16_t)dots[i].y);
        Write16(o + 4, 3);
        Write8(o + 6, (uint8_t)i);
    }
    Write8(st + 0x28, 0);   // WPAD_DEV_CORE
    Write8(st + 0x29, 0);
}
