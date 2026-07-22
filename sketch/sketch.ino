// SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
//
// SPDX-License-Identifier: MPL-2.0
//
// MCU side of the Programma 101 emulator: drives a physical Modulino Buzzer for keyboard click,
// error, and printer-chatter sound effects, plus the onboard LED matrix. All emulation logic lives
// on the Linux side; the MCU only ever receives a small RPC payload (a tone, or a matrix mode) and
// renders it -- it never blocks on or waits for anything happening on the Linux side. The matrix
// mirrors conquest-q's approach: a single mode id driven by Bridge, rendered as a pure function of
// millis() so it keeps animating even if the MPU is busy.

#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>
#include <Arduino_LED_Matrix.h>

ModulinoBuzzer buzzer;
Arduino_LED_Matrix matrix;

#define MODE_IDLE 0         // machine waiting for input: static Olivetti logo
#define MODE_CALCULATING 1  // a calculation is in flight: animated crossfade to the Elea logo

#define CROSSFADE_MS 400UL
#define PULSE_PERIOD_MS 1400UL

// 8x13 pure black & white bitmaps (0/1, one byte per pixel), downsampled from the Olivetti and
// Elea logos and thresholded to strict on/off -- this matrix doesn't render shades of gray well,
// so every pixel the MCU ever draws is fully lit or fully dark, never an intermediate brightness.
static const uint8_t OLIVETTI_FRAME[8 * 13] = {
  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
  0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0,
  0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0,
  0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0,
  0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0,
  0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0,
  0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0,
  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
};

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

uint8_t matrixMode = MODE_IDLE;
uint8_t prevMatrixMode = MODE_IDLE;
unsigned long matrixModeChangedAt = 0;
uint8_t frame[8 * 13];

const uint8_t *frameFor(uint8_t m) {
  return (m == MODE_CALCULATING) ? ELEA_FRAME : OLIVETTI_FRAME;
}

// Deterministic per-pixel "switch order" within the crossfade window: a dissolve transition flips
// each pixel from the old frame to the new one at a different moment instead of blending
// brightness, so every pixel the MCU ever writes is exactly 0 or 1, never an in-between shade.
uint8_t ditherRank(int i) {
  return (uint8_t)((i * 37) % (8 * 13));
}

// Triangle wave in [0, 1], used to gate a checkerboard dim mask while MODE_CALCULATING so the held
// Elea frame still visibly "breathes" during a long-running program, without ever emitting a gray
// pixel -- half the lit pixels blink off on a period instead of the whole frame dimming smoothly.
float triangleWave(unsigned long t) {
  unsigned long ph = t % PULSE_PERIOD_MS;
  float x = (float)ph / (float)PULSE_PERIOD_MS;
  return (x < 0.5f) ? (x * 2.0f) : (2.0f - x * 2.0f);
}

void renderMatrixFrame(unsigned long t) {
  const uint8_t *from = frameFor(prevMatrixMode);
  const uint8_t *to = frameFor(matrixMode);
  unsigned long elapsed = t - matrixModeChangedAt;

  if (elapsed < CROSSFADE_MS) {
    uint8_t cutoff = (uint8_t)(((unsigned long)(8 * 13) * elapsed) / CROSSFADE_MS);
    for (int i = 0; i < 8 * 13; i++) {
      frame[i] = (ditherRank(i) < cutoff) ? to[i] : from[i];
    }
    return;
  }

  if (matrixMode == MODE_CALCULATING) {
    bool dim = triangleWave(elapsed - CROSSFADE_MS) < 0.5f;
    for (int i = 0; i < 8 * 13; i++) {
      bool checker = ((i / 13 + i % 13) % 2) == 0;
      frame[i] = (dim && !checker) ? 0 : to[i];
    }
  } else {
    for (int i = 0; i < 8 * 13; i++) frame[i] = to[i];
  }
}

// RPC provided to the MPU: hw.py's Hardware._play(freq, ms) calls this via Bridge.call("play_tone", ...)
String playTone(int freq, int ms) {
  buzzer.tone(freq, ms);
  return "{\"ok\":true}";
}

// RPC provided to the MPU: hw.py's Hardware._set_matrix_mode(mode) calls this via
// Bridge.call("set_matrix_mode", ...)
String setMatrixMode(int newMode) {
  uint8_t m = (newMode == MODE_CALCULATING) ? MODE_CALCULATING : MODE_IDLE;
  if (m != matrixMode) {
    prevMatrixMode = matrixMode;
    matrixMode = m;
    matrixModeChangedAt = millis();
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
