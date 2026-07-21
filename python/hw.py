# SPDX-FileCopyrightText: Copyright (C) Programma 101 Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""Thin wrapper over a single Bridge RPC to the paired MCU, which drives a physical Modulino
Buzzer. All emulation logic stays on the Linux side; the MCU only ever receives a frequency and a
duration and plays that tone -- it never blocks on or waits for anything happening on the Linux
side. Mirrors conquest-q's Hardware wrapper: deferred Bridge import, and every call is wrapped by
the caller in a way that degrades to silent UI-only operation if no buzzer/MCU is attached.
"""

# Tones for the keyboard, in Hz/ms, matching a plausible mechanical-calculator click and the
# machine's own error chime.
TONE_KEY_CLICK = (1800, 15)
TONE_ERROR = (220, 250)
TONE_PRINT_CHATTER = (900, 20)
TONE_STARTUP = (1200, 80)


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
