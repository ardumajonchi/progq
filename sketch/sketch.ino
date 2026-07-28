// SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
//
// SPDX-License-Identifier: MPL-2.0
//
// MCU side of the Programma 101 emulator: drives a physical Modulino Buzzer for keyboard click,
// error, and printer-chatter sound effects, the onboard LED matrix (now doubling as a tape/output
// display), and -- all optional, degrade-safe exactly like the buzzer -- a Modulino Joystick,
// Modulino Buttons, and a second Modulino LED Matrix over Qwiic used as a physical control surface.
// All emulation logic lives on the Linux side; the MCU only ever receives a small RPC payload (a
// tone, a matrix mode, or a string to scroll) and renders it, or reports a raw input edge over
// Bridge.notify -- it never blocks on or waits for anything happening on the Linux side. The Elea
// logo animation mirrors conquest-q's approach: a mode flag driven by Bridge, rendered as a pure
// function of millis() so it keeps animating even if the MPU is busy; the new tape/menu scroll text
// is layered on top using ArduinoGraphics, priority-gated so an in-flight Elea flash always wins.

#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>
#include <Modulino_LED_Matrix.h>  // ModulinoLEDMatrix -- not pulled in by Arduino_Modulino.h itself
#include <Arduino_LED_Matrix.h>
#include <ArduinoGraphics.h>

ModulinoBuzzer buzzer;
Arduino_LED_Matrix matrix;

// Physical control surface -- each is entirely optional; `has*` gates every use, same
// degrade-to-silent/no-op pattern as the buzzer when a Brick/MCU peripheral isn't attached.
ModulinoButtons buttons(0x3E);
ModulinoJoystick joystick(0x2C);
ModulinoLEDMatrix qwiicMatrix;
bool hasButtons = false;
bool hasJoystick = false;
bool hasQwiicMatrix = false;

#define POLL_INTERVAL_MS 16UL  // ~60 Hz input poll, matches the matrix's own draw cadence
#define TAPE_SCROLL_MS 120UL   // how long each 1px scroll step of tape/menu text holds on screen

#define MODE_IDLE 0         // no calculation in flight: static Elea logo, fully assembled
#define MODE_CALCULATING 1  // a calculation (single key or a running program) is in flight

// Latest strings to scroll on the onboard (tape) and Qwiic (menu/status) matrices, set via the
// setTapeText/setMenuText RPCs below. Each matrix tracks its own scroll position/timer so the two
// scroll independently of each other and of the Elea animation's own clock.
String tapeText = "";
String menuText = "";
int tapeScrollX = 0;
int menuScrollX = 0;
unsigned long lastTapeAdvanceAt = 0;
unsigned long lastMenuAdvanceAt = 0;
unsigned long lastPollAt = 0;

#define REBUILD_MS 350UL       // how long the quick "rebuild" reveal takes for one calculation
#define PULSE_PERIOD_MS 900UL  // breathing period while a longer-running program keeps calculating

// 8x13 pure black & white bitmap (0/1, one byte per pixel) of the Elea 9000 logo -- Olivetti's
// mainframe computer line, and the direct ancestor of Arduino's own Ivrea, Italy design lineage
// (see the README's History section). This is the only image the matrix ever shows at rest: idle
// holds it fully lit, and every calculation replays a quick rebuild of it from blank to complete,
// as if the machine were re-deriving the logo alongside the result.
static const uint8_t ELEA_FRAME[8 * 13] = {
  1, 1, 0, 1, 0, 0, 1, 1, 0, 1, 0, 0, 1,
  0, 0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 0,
  0, 0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0, 0,
  1, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1,
  1, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1,
  0, 0, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0, 0,
  0, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 0,
  1, 1, 0, 1, 0, 0, 1, 1, 0, 1, 0, 1, 1,
};

bool calculating = false;         // true for the duration of a running program (V/W/Y/Z)
unsigned long calcStartedAt = 0;  // millis() timestamp of the most recent rebuild trigger
uint8_t frame[8 * 13];

// Deterministic per-pixel "build order" for the rebuild reveal: each lit pixel of ELEA_FRAME turns
// on at a different moment within REBUILD_MS instead of the whole image fading in at once, so
// every pixel the MCU ever writes is exactly 0 or 1, never an in-between shade.
uint8_t buildRank(int i) {
  return (uint8_t)((i * 37) % (8 * 13));
}

// Triangle wave in [0, 1], used to gate a checkerboard dim mask so a long-running program still
// visibly "breathes" once fully rebuilt, without ever emitting a gray pixel -- half the lit pixels
// blink off on a period instead of the whole frame dimming smoothly.
float triangleWave(unsigned long t) {
  unsigned long ph = t % PULSE_PERIOD_MS;
  float x = (float)ph / (float)PULSE_PERIOD_MS;
  return (x < 0.5f) ? (x * 2.0f) : (2.0f - x * 2.0f);
}

// Renders into frame[] and returns true whenever the Elea rebuild/breathing flash is in flight --
// this always takes priority. Returns false when idle, at which point the caller renders the tape
// scroll instead of the old static idle logo (see renderScrollText below).
bool renderMatrixFrame(unsigned long t) {
  unsigned long sinceTrigger = t - calcStartedAt;

  // The rebuild reveal always plays out in full over REBUILD_MS from the moment it was triggered,
  // even if the calculation itself (often a single key press) finished on the Linux side well
  // before that -- otherwise a fast single-key calculation would never render more than one frame.
  if (sinceTrigger < REBUILD_MS) {
    uint8_t cutoff = (uint8_t)(((unsigned long)(8 * 13) * sinceTrigger) / REBUILD_MS);
    for (int i = 0; i < 8 * 13; i++) {
      frame[i] = (buildRank(i) < cutoff) ? ELEA_FRAME[i] : 0;
    }
    return true;
  }

  if (calculating) {
    bool dim = triangleWave(sinceTrigger - REBUILD_MS) < 0.5f;
    for (int i = 0; i < 8 * 13; i++) {
      bool checker = ((i / 13 + i % 13) % 2) == 0;
      frame[i] = (dim && !checker) ? 0 : ELEA_FRAME[i];
    }
    return true;
  }

  return false;
}

// Scrolls `text` one pixel to the left every TAPE_SCROLL_MS on any ArduinoGraphics-backed matrix
// (the onboard Arduino_LED_Matrix or the Qwiic ModulinoLEDMatrix). Deliberately never calls
// ArduinoGraphics::endText(SCROLL_LEFT) -- that call blocks for the whole scroll via delay(), which
// would stall loop() and Bridge servicing. Driving the offset from millis() and rendering a single
// still frame each tick (endText(NO_SCROLL)) keeps this non-blocking like everything else here.
template <typename MatrixT>
void renderScrollText(MatrixT &m, const String &text, int &scrollX, unsigned long &lastAdvanceAt,
                      unsigned long t, int width) {
  if (text.length() == 0) {
    m.beginDraw();
    m.clear();
    m.endDraw();
    return;
  }
  if (t - lastAdvanceAt >= TAPE_SCROLL_MS) {
    lastAdvanceAt = t;
    scrollX--;
    int textWidth = text.length() * 5;  // Font_5x7 glyph advance width in pixels
    if (scrollX < -textWidth) scrollX = width;
  }
  m.beginDraw();
  m.textFont(Font_5x7);
  m.beginText(scrollX, 1, 0xffffff);
  m.print(text);
  m.endText(NO_SCROLL);
  m.endDraw();
}

// RPC provided to the MPU: hw.py's Hardware._play(freq, ms) calls this via Bridge.call("play_tone", ...)
String playTone(int freq, int ms) {
  buzzer.tone(freq, ms);
  return "{\"ok\":true}";
}

// RPC provided to the MPU: hw.py's Hardware._set_matrix_mode(mode) calls this via
// Bridge.call("set_matrix_mode", ...). MODE_CALCULATING (re)triggers the rebuild reveal from
// scratch -- called once per single-key calculation and once at the start of a full program run --
// so rapid presses each get their own quick rebuild rather than piling into one animation.
// MODE_IDLE ends a program run's breathing once it actually completes; a rebuild reveal already in
// flight is never cut short by this, since it's timed independently of the `calculating` flag.
String setMatrixMode(int newMode) {
  if (newMode == MODE_CALCULATING) {
    calculating = true;
    calcStartedAt = millis();
  } else {
    calculating = false;
  }
  return "{\"ok\":true}";
}

// RPC provided to the MPU: hw.py's Hardware.set_tape_text(text) calls this via
// Bridge.call("set_tape_text", ...) to update the string scrolled on the onboard matrix whenever
// the Elea flash isn't in flight (see loop()).
String setTapeText(String text) {
  if (text != tapeText) {
    tapeText = text;
    tapeScrollX = 0;
  }
  return "{\"ok\":true}";
}

// RPC provided to the MPU: hw.py's Hardware.set_menu_text(text) calls this via
// Bridge.call("set_menu_text", ...) to update the physical-control status line scrolled on the
// optional Qwiic matrix. No-op target if !hasQwiicMatrix -- loop() simply never renders it.
String setMenuText(String text) {
  if (text != menuText) {
    menuText = text;
    menuScrollX = 0;
  }
  return "{\"ok\":true}";
}

void setup() {
  Bridge.begin();
  Modulino.begin();
  buzzer.begin();
  Bridge.provide("play_tone", playTone);

  matrix.begin();
  matrix.setGrayscaleBits(1);  // frame[] is strictly 0/1 now -- 1 must mean fully lit, not 1/7 dim
  Bridge.provide("set_matrix_mode", setMatrixMode);
  Bridge.provide("set_tape_text", setTapeText);
  Bridge.provide("set_menu_text", setMenuText);

  hasButtons = buttons.begin();
  hasJoystick = joystick.begin();
  hasQwiicMatrix = qwiicMatrix.begin();
}

// Polls the optional physical control surface at ~60 Hz and reports only actual edges over
// Bridge.notify -- mirrors the modulino-hid-bridge reference sketch's event style. Python
// (main.py) turns each event into the same _apply_key-shaped dict a browser click or the AI
// Operator would produce, so physical input is just another hand on the keyboard.
void pollControls(unsigned long t) {
  if (t - lastPollAt < POLL_INTERVAL_MS) return;
  lastPollAt = t;

  if (hasButtons && buttons.update()) {
    Bridge.notify("btn_event", (int)buttons.isPressed(0), (int)buttons.isPressed(1), (int)buttons.isPressed(2));
  }
  if (hasJoystick && joystick.update()) {
    Bridge.notify("joy_event", (int)joystick.getX(), (int)joystick.getY(), (int)joystick.isPressed());
  }
}

void loop() {
  unsigned long t = millis();
  pollControls(t);

  if (renderMatrixFrame(t)) {
    matrix.draw(frame);
  } else {
    renderScrollText(matrix, tapeText, tapeScrollX, lastTapeAdvanceAt, t, 13);
  }

  if (hasQwiicMatrix) {
    renderScrollText(qwiicMatrix, menuText, menuScrollX, lastMenuAdvanceAt, t, 12);
  }
}
