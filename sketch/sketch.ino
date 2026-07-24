// SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
//
// SPDX-License-Identifier: MPL-2.0
//
// MCU side of the Programma 101 emulator: drives a physical Modulino Buzzer for keyboard click,
// error, and printer-chatter sound effects, plus the onboard LED matrix. All emulation logic lives
// on the Linux side; the MCU only ever receives a small RPC payload (a tone, or a matrix mode) and
// renders it -- it never blocks on or waits for anything happening on the Linux side. The matrix
// mirrors conquest-q's approach: a mode flag driven by Bridge, rendered as a pure function of
// millis() so it keeps animating even if the MPU is busy.

#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>
#include <Arduino_LED_Matrix.h>

ModulinoBuzzer buzzer;
Arduino_LED_Matrix matrix;

#define MODE_IDLE 0         // no calculation in flight: static Elea logo, fully assembled
#define MODE_CALCULATING 1  // a calculation (single key or a running program) is in flight

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

void renderMatrixFrame(unsigned long t) {
  unsigned long sinceTrigger = t - calcStartedAt;

  // The rebuild reveal always plays out in full over REBUILD_MS from the moment it was triggered,
  // even if the calculation itself (often a single key press) finished on the Linux side well
  // before that -- otherwise a fast single-key calculation would never render more than one frame.
  if (sinceTrigger < REBUILD_MS) {
    uint8_t cutoff = (uint8_t)(((unsigned long)(8 * 13) * sinceTrigger) / REBUILD_MS);
    for (int i = 0; i < 8 * 13; i++) {
      frame[i] = (buildRank(i) < cutoff) ? ELEA_FRAME[i] : 0;
    }
    return;
  }

  if (calculating) {
    bool dim = triangleWave(sinceTrigger - REBUILD_MS) < 0.5f;
    for (int i = 0; i < 8 * 13; i++) {
      bool checker = ((i / 13 + i % 13) % 2) == 0;
      frame[i] = (dim && !checker) ? 0 : ELEA_FRAME[i];
    }
    return;
  }

  for (int i = 0; i < 8 * 13; i++) frame[i] = ELEA_FRAME[i];
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

void setup() {
  Bridge.begin();
  Modulino.begin();
  buzzer.begin();
  Bridge.provide("play_tone", playTone);

  matrix.begin();
  matrix.setGrayscaleBits(1);  // frame[] is strictly 0/1 now -- 1 must mean fully lit, not 1/7 dim
  Bridge.provide("set_matrix_mode", setMatrixMode);
}

void loop() {
  renderMatrixFrame(millis());
  matrix.draw(frame);
}
