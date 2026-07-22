# Programma 101

A web-based emulator of the Olivetti Programma 101, the 1965 programmable desktop
calculator/proto-PC. Built on the official `arduino:web_ui` and `arduino:dbstorage_sqlstore`
Bricks, with keyboard-click sound effects on a physical Modulino Buzzer and the Olivetti/Elea
logos animating on the UNO Q's onboard LED matrix.

![Programma 101 UI](docs/screenshot.png)

*The panel mid-way through the bundled "Countdown demo" card: the tape shows the counted-down
values ending at `0`, register A holds `-1` (the loop's final decrement past zero) and M holds `1`
(the step size).*

## Running it

Deploy with the Arduino App CLI like any other app Brick bundle (`app.yaml` declares the
`arduino:web_ui` and `arduino:dbstorage_sqlstore` Bricks and exposes port 7000). Once deployed,
open the app's URL (`http://<device-ip>:7000/`) in a browser to use it. Attach a Modulino Buzzer
to the paired MCU for keyboard-click, error, and printer-chatter sounds — the app runs fine
without one, silently skipping the tones. The onboard LED matrix shows the Olivetti logo while
idle and crossfades into a pulsing Elea logo while a program (`V`/`W`/`Y`/`Z`) is running,
degrading to no matrix updates the same way the buzzer does if the MCU isn't attached.

## User guide

The panel mirrors the real machine's control layout: a scrolling tape strip along the top logs
every keystroke and printed result, register readouts below it show the entry buffer and the
live A, M, and R registers, and an error box lights up with a message whenever the machine
blocks on an error.

### Basic arithmetic (calculator mode)

The Programma 101 always computes against the **A** (accumulator) register. A typical calculation
looks like: type a number on the numeric keypad, press an operation key, type another number,
press another operation key, then press the print key to read the result off the tape.

1. **Type digits** on the numeric keypad (`0`-`9` and `.`) — they accumulate in the **entry
   buffer**, shown in the ENTRY readout. Nothing is committed to a register yet.
2. **Press an operation key** (`+`, `−`, `×`, `÷`, `√`, `A↓`, `Â`, `◇`, `✳`) to execute it
   immediately: with no register selected, the typed entry buffer is used as the operand against
   A; the entry buffer is then cleared.
3. **Select a register first** (optional) by pressing one of the register keys (`F`, `E`, `D`,
   `C`, `M`, `B`) — it highlights to show it's selected — then press an operation key to use that
   register's value as the operand instead of the entry buffer. Pressing the same register key
   again deselects it.
4. **`◇` (print)** writes the current value of A (or the selected register) to the tape.
5. **`✳` (clear)** zeroes out A (or the selected register).
6. **`S`** is Stop/Acknowledge: press it to clear a blocked error state (see below), or to halt a
   running program.

Example — add 7 and 3, then print the result: type `7`, press `+`, type `3`, press `+`, press
`◇`. The tape shows `+`, `+`, then `10`.

### Register keys and SPLIT

`F`, `E`, `D`, `C`, `M`, `B` select a register as the operand for the next operation key. **SPLIT**
splits or unsplits one of `B`, `C`, `D`, `E`, `F` into two independent half-capacity registers
(you'll be prompted for which register) — a feature of the real machine used by programs that
need two smaller values instead of one large one.

### Blocked/error states

Dividing by zero, taking the square root of a negative number, or overflowing a register's digit
capacity blocks the machine exactly as it did in 1965: the ERROR readout lights up with a
message and further operation keys are ignored until you press **S** to acknowledge and clear it.

### Recording and saving a program

1. Press **REC** to enter recording mode. Digit and operator key presses are now appended to an
   in-progress program instead of executing immediately — the STEP counter tracks how many
   instructions you've recorded.
2. Press one of **V=1 / W=2 / Y=3 / Z=4** at any point while recording to mark the *current* step
   as that label's entry point — this is what a later **V/W/Y/Z** start-key press will jump to.
3. Type a title into the **Card title** field and press **SAVE AS CARD** to commit the recorded
   program: it's saved to the CARDS list, loaded as the active program, and recording mode turns
   off.

### Running a saved program

Press one of the **V / W / Y / Z** start keys to run the loaded program from that key's label
until it hits a `stop` instruction, an error, or runs off the end. Every value the program prints
along the way appears on the tape.

### Managing cards

The **CARDS** panel lists every saved card — click a title to load it as the active program, or
click **✕** to delete it. A demo countdown program (see below) is seeded automatically on first
run.

### Tape and entry controls

**CLR ENT** clears the typed-but-not-committed entry buffer without touching any register.
**CLR TAPE** clears the tape display. **SHARE TAPE** downloads the current tape's full contents
as a text file.

## The bundled "Countdown demo" card

Every fresh install seeds one demo card, `Countdown demo`, matching the classic demo EMU101
itself ships. It implements a simple count-down-by-one loop:

| Step | Instruction | Effect |
|---|---|---|
| 0 (label `V`) | print A | Print the current value of A to the tape |
| 1 | subtract M from A | Decrement A by the value in M |
| 2 | conditional jump to label `Z` | If the last result went negative, jump to step 4 (stop) |
| 3 | jump to label `V` | Otherwise loop back to step 0 |
| 4 (label `Z`) | stop | Halt |

To run it from a clean start: select **M**, type `1`, press **A↓** (transfer to M) — this sets the
decrement step size to 1 — then select **A**, type your starting number (e.g. `10`), press `+` to
commit it into A, load the "Countdown demo" card from the CARDS panel if it isn't already loaded,
and press **V**. The tape prints each value counting down from your starting number to `0`, then
one more decrement pushes A negative, the conditional jump fires, and the program stops — leaving
A at `-1` and M at `1`, exactly as shown in the screenshot above.

## How it works

- **Emulation core.** `python/engine/` is a clean-room reimplementation of the Programma 101's
  documented register model, instruction set, and card format — written from the real machine's
  published specifications, not derived from any existing emulator's source. `registers.py` models
  the ten registers (M, A, R, B, C, D, E, F, p1, p2) as exact-decimal values via Python's `Decimal`,
  enforcing the real 22-digit (11-digit when split) capacity limits. `instructions.py` defines the
  instruction vocabulary and start-key/label table. `cpu.py`'s `Machine` executes one instruction
  at a time in either interactive (calculator) mode or full-program mode, raising the real
  machine's documented blocking conditions (division by zero, negative square root, overflow) the
  same way the original halts and waits for the operator to press S. `cards.py` and `printer.py`
  handle program-card and tape formatting respectively.
- **Persistence.** `python/cardstore.py` wraps the `arduino:dbstorage_sqlstore` Brick to save/load/
  delete named program cards, with every query touching a user-supplied title going through bound
  parameters (`execute_sql` with `?` placeholders) rather than a raw condition string.
- **Web UI.** `assets/` is a click-driven skeuomorphic control panel served by the `arduino:web_ui`
  Brick over Socket.IO — every key is a real click target sending a small JSON payload (see
  `python/main.py`'s module docstring for the exact message protocol); the server always answers
  with a full state broadcast (tape, registers, entry buffer, recording state, card list).
- **Sound.** `sketch/` runs on the paired MCU and drives a physical Modulino Buzzer via a single
  `play_tone(freq, ms)` Bridge RPC; `python/hw.py` calls it for keyboard clicks, errors, and
  printer chatter, degrading to silent UI-only operation if no buzzer/MCU is attached.
- **LED matrix.** The same `sketch/` also drives the UNO Q's onboard LED matrix via a single
  `set_matrix_mode(mode)` Bridge RPC, mirroring conquest-q's approach: the MCU renders the current
  mode as a pure function of `millis()`, so the animation never blocks on or waits for the Linux
  side. `python/hw.py`'s `show_idle()`/`show_calculating()` toggle the mode; `python/main.py` calls
  `show_calculating()` before `Machine.run_from()` and `show_idle()` after, so the matrix reflects
  whether the emulator is idle or a program is running. The idle mode shows a static, downsampled
  8x13 rendering of the Olivetti logo; the calculating mode crossfades into the Elea logo and
  pulses its brightness while active.
