# SPDX-FileCopyrightText: Copyright (C) Programma 101 Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""Thin wrapper over Bridge RPCs to the paired MCU, which drives a physical Modulino Buzzer and the
onboard LED matrix. All emulation logic stays on the Linux side; the MCU only ever receives a
frequency/duration pair or a matrix mode id and renders it -- it never blocks on or waits for
anything happening on the Linux side. Mirrors conquest-q's Hardware wrapper: deferred Bridge
import, and every call is wrapped by the caller in a way that degrades to silent UI-only operation
if no buzzer/MCU is attached.
"""

# Tones for the keyboard, in Hz/ms, matching a plausible mechanical-calculator click and the
# machine's own error chime.
TONE_KEY_CLICK = (1800, 15)
TONE_ERROR = (220, 250)
TONE_PRINT_CHATTER = (900, 20)
TONE_STARTUP = (1200, 80)

# LED matrix modes, matching sketch.ino's MODE_* constants.
MATRIX_MODE_IDLE = 0
MATRIX_MODE_CALCULATING = 1


class Hardware:
    def __init__(self):
        from arduino.app_utils import Bridge  # deferred: only required when actually running on-device

        self._bridge = Bridge

    def _play(self, freq: int, ms: int) -> None:
        try:
            self._bridge.call("play_tone", freq, ms)
        except Exception as exc:
            # The MCU may still be booting/flashing right after a restart, or the sketch may not
            # be attached at all during dev -- the buzzer is cosmetic and must never take the
            # emulator down with it.
            print(f"[progq] play_tone({freq}, {ms}) failed, MCU not ready: {exc!r}")

    def play_click(self) -> None:
        self._play(*TONE_KEY_CLICK)

    def play_error(self) -> None:
        self._play(*TONE_ERROR)

    def play_print_chatter(self) -> None:
        self._play(*TONE_PRINT_CHATTER)

    def play_startup(self) -> None:
        self._play(*TONE_STARTUP)

    def _set_matrix_mode(self, mode: int) -> None:
        try:
            self._bridge.call("set_matrix_mode", mode)
        except Exception as exc:
            # Cosmetic, same rationale as _play: never take the emulator down with it.
            print(f"[progq] set_matrix_mode({mode}) failed, MCU not ready: {exc!r}")

    def show_idle(self) -> None:
        self._set_matrix_mode(MATRIX_MODE_IDLE)

    def show_calculating(self) -> None:
        self._set_matrix_mode(MATRIX_MODE_CALCULATING)
