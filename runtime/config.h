#pragma once
#include <string>

// User settings loaded from config.ini next to the executable (created with
// defaults on first run). Command line options override them.
struct Config
{
    // [Video]
    int frameRate = 30;          // 30 (original) or 60
    int internalScale = 3;       // EFB resolution multiplier (1 = 640x528)
    int windowWidth = 1280;
    int windowHeight = 720;
    bool fullscreen = false;
    bool vsync = false;
    bool widescreen = true;
    int anisotropy = 1;          // forced anisotropic filtering (1 = as the game sets it)
    bool asyncShaders = true;    // compile new shaders in the background (no hitches)
    bool gpuThread = true;       // GX processing/rendering on its own thread
    bool texturePack = true;     // load Dolphin-format custom textures if present
    std::string texturePackDir;  // empty: <exe>/textures, game/textures, Dolphin's Load/Textures
    // [System]
    int language = 1;                // Wii IPL.LNG: 0 ja, 1 en, 2 de, 3 fr, 4 es, 5 it, 6 nl
    bool pauseOnFocusLoss = false;   // freeze the game while the window is in the background
    // [Input]
    bool rumble = true;
    bool remoteSpeaker = true;   // play Wii Remote speaker sounds on the PC
    float tiltRange = 60.0f;     // steering: Wii Remote roll (degrees) at full stick deflection
    float tiltSign = 1.0f;       // -1 swaps the steering direction
    // false (default): Sonic runs only while the left stick is pushed (or the brake button,
    // then "run", is held) and stops when it is released, as in the GameBanana Xbox
    // controls mod and Project Reignition. true: he runs on his own, as on the Wii.
    bool autoRun = false;
    // button bindings, action -> controller button name (A, B, X, Y, LB, RB, LT, RT,
    // START, BACK, LS, RS, UP, DOWN, LEFT, RIGHT or NONE); see config.cpp for actions.
    // Defaults follow the GameBanana Xbox controls mod (gamebanana.com/mods/390496):
    // A jump, B brake/run, X shake, Start = + and Wii A. Also built in: the right stick
    // steers, thrusts (down: homing attack) and tilts back (up), LB/RB steer when not
    // bound, LT+RT together shake. Wii B and "-" are unbound: BACK (the View button)
    // opens the settings overlay.
    std::string bind[12] = { "A", "NONE", "B", "X", "START", "NONE", "START", "NONE", "LS", "RS", "NONE", "NONE" };
    // [Keyboard] keyboard and mouse bindings: the 12 actions above, then HOME, the D-pad
    // and the movement stick (see kKeyActions). Each is a comma-separated list of key
    // names (SPACE, J, LSHIFT, MOUSE1, ...; see input/gamepad.cpp) or NONE.
    std::string keys[21] = { "SPACE", "J, MOUSE1", "K", "L", "LSHIFT, MOUSE2", "Q", "ENTER", "BACKSPACE", "NONE", "NONE",
                             "U", "NONE", "H", "UP", "DOWN", "LEFT", "RIGHT", "W", "S", "A", "D" };
    // [Paths]
    std::string dataDir;
    std::string isoPath;
};

extern Config g_config;

extern const char* const kBindActions[12];
extern const char* const kKeyActions[21];   // config.ini names of Config::keys

// Loads config.ini (writing the defaults if it does not exist) and remembers its path.
void Config_Load(const std::string& path);
// Writes the current g_config back to config.ini (with comments).
bool Config_Save();
const std::string& Config_Path();
std::string Config_Text(const Config& c);
