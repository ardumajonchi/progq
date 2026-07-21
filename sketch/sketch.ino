// SPDX-FileCopyrightText: Copyright (C) Programma 101 Emulator contributors
//
// SPDX-License-Identifier: MPL-2.0
//
// MCU side of the Programma 101 emulator: drives a physical Modulino Buzzer for keyboard click,
// error, and printer-chatter sound effects. All emulation logic lives on the Linux side; the MCU
// only ever receives a frequency/duration pair and plays exactly that tone, once, then returns --
// it never blocks on or waits for anything happening on the Linux side.

#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>

ModulinoBuzzer buzzer;

// RPC provided to the MPU: hw.py's Hardware._play(freq, ms) calls this via Bridge.call("play_tone", ...)
String playTone(int freq, int ms) {
  buzzer.tone(freq, ms);
  return "{\"ok\":true}";
}

void setup() {
  Bridge.begin();
  Modulino.begin();
  buzzer.begin();
  Bridge.provide("play_tone", playTone);
}

void loop() {
}
