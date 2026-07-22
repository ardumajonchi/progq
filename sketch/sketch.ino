// SPDX-FileCopyrightText: Copyright (C) Programma 101 Emulator contributors
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

// 8x13 grayscale bitmaps (0-4, one byte per pixel), downsampled from the Olivetti and Elea logos.
static const uint8_t OLIVETTI_FRAME[8 * 13] = {
  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
  0, 0, 1, 3, 2, 3, 3, 3, 2, 3, 1, 0, 0,
  0, 0, 2, 4, 3, 3, 3, 3, 3, 4, 2, 0, 0,
  0, 0, 2, 3, 4, 1, 0, 1, 3, 3, 2, 0, 0,
  0, 0, 2, 3, 3, 3, 2, 3, 4, 4, 3, 1, 0,
  0, 0, 2, 4, 3, 3, 3, 4, 3, 4, 2, 0, 0,
  0, 0, 1, 2, 2, 2, 2, 2, 2, 3, 1, 0, 0,
  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
};

static const uint8_t ELEA_FRAME[8 * 13] = {
  3, 3, 0, 3, 2, 2, 4, 3, 1, 3, 0, 2, 3,
  1, 2, 3, 4, 3, 3, 2, 3, 3, 4, 3, 3, 1,
  2, 2, 4, 4, 4, 3, 2, 3, 4, 4, 4, 2, 2,
  3, 3, 2, 3, 2, 3, 3, 3, 2, 3, 2, 3, 3,
  3, 3, 2, 3, 2, 3, 3, 3, 2, 3, 2, 3, 3,
  2, 2, 4, 4, 4, 3, 2, 3, 4, 4, 4, 2, 2,
  1, 3, 3, 4, 3, 3, 2, 3, 3, 4, 3, 3, 1,
  3, 3, 0, 3, 1, 2, 4, 3, 1, 3, 0, 3, 3,
};

uint8_t matrixMode = MODE_IDLE;
uint8_t prevMatrixMode = MODE_IDLE;
unsigned long matrixModeChangedAt = 0;
uint8_t frame[8 * 13];

const uint8_t *frameFor(uint8_t m) {
  return (m == MODE_CALCULATING) ? ELEA_FRAME : OLIVETTI_FRAME;
}

// Triangle-wave brightness multiplier, so a held Elea frame still reads as "working" rather than
// looking identical to a finished/frozen render during a longer program run.
float pulseFactor(unsigned long t) {
  unsigned long ph = t % PULSE_PERIOD_MS;
  float x = (float)ph / (float)PULSE_PERIOD_MS;
  float tri = (x < 0.5f) ? (x * 2.0f) : (2.0f - x * 2.0f);
  return 0.6f + 0.4f * tri;
}

void renderMatrixFrame(unsigned long t) {
  const uint8_t *from = frameFor(prevMatrixMode);
  const uint8_t *to = frameFor(matrixMode);
  unsigned long elapsed = t - matrixModeChangedAt;

  if (elapsed >= CROSSFADE_MS) {
    if (matrixMode == MODE_CALCULATING) {
      float factor = pulseFactor(t - matrixModeChangedAt - CROSSFADE_MS);
      for (int i = 0; i < 8 * 13; i++) frame[i] = (uint8_t)(to[i] * factor + 0.5f);
    } else {
      for (int i = 0; i < 8 * 13; i++) frame[i] = to[i];
    }
    return;
  }

  float alpha = (float)elapsed / (float)CROSSFADE_MS;
  for (int i = 0; i < 8 * 13; i++) {
    frame[i] = (uint8_t)(from[i] + (to[i] - from[i]) * alpha + 0.5f);
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
  matrix.setGrayscaleBits(3);
  Bridge.provide("set_matrix_mode", setMatrixMode);
}

void loop() {
  renderMatrixFrame(millis());
  matrix.draw(frame);
}
