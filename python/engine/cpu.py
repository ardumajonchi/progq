# SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""CPU: executes Programma 101 instructions against a RegisterFile, in both interactive
("calculator mode" -- one key press at a time) and program mode (`run_from()` executes a stored
program from one of the four start-key labels until STOP). Clean-room reimplementation against the
machine's documented instruction semantics and error/blocking conditions -- not a translation of
any existing emulator's source.
"""

from __future__ import annotations

from decimal import Decimal, getcontext

from .instructions import (
    ARITHMETIC_OPS,
    Instruction,
    OP_ADD,
    OP_CLEAR,
    OP_COND_JUMP,
    OP_DECIMAL_PART,
    OP_DIGIT,
    OP_DIV,
    OP_EXCHANGE_A,
    OP_JUMP,
    OP_MUL,
    OP_PRINT,
    OP_RS,
    OP_SQRT,
    OP_STOP,
    OP_SUB,
    OP_TRANSFER_TO_M,
    START_KEYS,
)
from .registers import RegisterFile

# Generous working precision for intermediate division/sqrt results, so repeating decimals don't
# get truncated before we round down to the real machine's 15-decimal-place display limit.
getcontext().prec = 60

_DISPLAY_QUANTUM = Decimal("1e-15")


class CpuError(Exception):
    """A documented P101 blocking condition: division by zero, sqrt of a negative number, or a
    result too large for a register. The real machine halts and waits for the operator to press
    S to acknowledge; we surface the same halt via `Machine.blocked_error`."""


def _round_to_capacity(value: Decimal) -> Decimal:
    """Round to the real machine's 15-decimal-place display limit, in plain (non-scientific)
    notation, so downstream digit-count capacity checks see genuine significant digits."""
    quantized = value.quantize(_DISPLAY_QUANTUM)
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return Decimal(text) if text else Decimal(0)


class Machine:
    """Holds the register file, the typed-but-not-yet-committed entry buffer, an optional loaded
    program, and the four label-addressable start points (V, W, Y, Z)."""

    def __init__(self) -> None:
        self.registers = RegisterFile()
        self.entry: str = ""
        self.program: list[Instruction] = []
        self.labels: dict[int, int] = {}
        self.pc: int = 0
        self.running: bool = False
        self.blocked_error: str | None = None
        self.sign_flag: bool = False

    # -- interactive ("calculator mode") entry -------------------------------------------------

    def key_digit(self, ch: str) -> None:
        if ch not in "0123456789.":
            raise ValueError(f"not a digit key: {ch!r}")
        if ch == "." and "." in self.entry:
            raise ValueError("entry already has a decimal point")
        self.entry += ch

    def clear_entry(self) -> None:
        self.entry = ""

    def commit_entry(self, register_name: str) -> None:
        """Transfer the typed entry buffer straight into a register (the real machine's
        register-select-then-type-digits data-entry flow)."""
        value = Decimal(self.entry) if self.entry else Decimal(0)
        self.registers[register_name].set(value)
        self.entry = ""

    def press_key(self, operator: str, register: str | None = None) -> str | None:
        """Execute a single instruction immediately, outside of a running program -- the
        interactive calculator-mode flow. Returns a tape line for OP_PRINT, else None."""
        instr = Instruction(operator=operator, register=register)
        try:
            result = self.execute(instr)
            self.blocked_error = None
            return result
        except CpuError as exc:
            self.blocked_error = str(exc)
            raise

    def acknowledge_error(self) -> None:
        """The real machine's S key, pressed to clear a blocked/error state."""
        self.blocked_error = None
        self.entry = ""

    # -- program mode ---------------------------------------------------------------------------

    def load_program(self, instructions: list[Instruction], labels: dict[int, int]) -> None:
        self.program = instructions
        self.labels = dict(labels)
        self.pc = 0

    def run_from(self, start_key: str, max_steps: int = 100_000) -> list[str]:
        """Run the loaded program from a start key's label until STOP, an error, or falling off
        the end of the program. Returns every tape line printed along the way."""
        if start_key not in START_KEYS:
            raise ValueError(f"not a start key: {start_key!r}")
        label = START_KEYS[start_key]
        if label not in self.labels:
            raise CpuError(f"label for start key {start_key} is not defined")
        self.pc = self.labels[label]
        self.running = True
        self.blocked_error = None
        printed: list[str] = []
        steps = 0
        while self.running:
            if self.pc >= len(self.program):
                self.running = False
                break
            instr = self.program[self.pc]
            self.pc += 1
            try:
                result = self.execute(instr)
            except CpuError as exc:
                self.running = False
                self.blocked_error = str(exc)
                break
            if result is not None:
                printed.append(result)
            if instr.operator == OP_STOP:
                self.running = False
            steps += 1
            if steps > max_steps:
                raise CpuError("runaway program: exceeded max step count without a STOP")
        return printed

    # -- instruction execution --------------------------------------------------------------

    def execute(self, instr: Instruction) -> str | None:
        op = instr.operator
        reg = self.registers[instr.register] if instr.register else None

        if op == OP_DIGIT:
            self.key_digit(str(instr.operand))
            return None

        if op in ARITHMETIC_OPS:
            accumulator = self.registers["A"]
            operand_value = reg.get() if reg is not None else Decimal(self.entry or "0")
            a_value = accumulator.get()
            if op == OP_ADD:
                result = a_value + operand_value
            elif op == OP_SUB:
                result = a_value - operand_value
            elif op == OP_MUL:
                result = a_value * operand_value
            elif op == OP_DIV:
                if operand_value == 0:
                    raise CpuError("division by zero")
                result = a_value / operand_value
            else:  # pragma: no cover - exhaustive over ARITHMETIC_OPS
                raise CpuError(f"unhandled arithmetic operator {op}")
            result = _round_to_capacity(result)
            try:
                accumulator.set(result)
            except Exception as exc:
                raise CpuError(f"overflow: {exc}") from exc
            self.sign_flag = accumulator.get() < 0
            self.entry = ""
            return None

        if op == OP_SQRT:
            target = reg if reg is not None else self.registers["A"]
            value = target.get()
            if value < 0:
                raise CpuError("square root of a negative number")
            target.set(_round_to_capacity(value.sqrt()))
            return None

        if op == OP_TRANSFER_TO_M:
            source = reg if reg is not None else self.registers["A"]
            self.registers["M"].set(source.get())
            return None

        if op == OP_EXCHANGE_A:
            if reg is None:
                raise CpuError("exchange-with-A requires a register operand")
            accumulator = self.registers["A"]
            a_value, reg_value = accumulator.get(), reg.get()
            accumulator.set(reg_value)
            reg.set(a_value)
            return None

        if op == OP_DECIMAL_PART:
            target = reg if reg is not None else self.registers["A"]
            value = target.get()
            target.set(value - int(value))
            return None

        if op == OP_CLEAR:
            (reg if reg is not None else self.registers["A"]).clear()
            self.entry = ""
            return None

        if op == OP_PRINT:
            source = reg if reg is not None else self.registers["A"]
            return str(source.get())

        if op == OP_STOP:
            return None

        if op == OP_RS:
            d_reg, r_reg = self.registers["D"], self.registers["R"]
            d_value, r_value = d_reg.get(), r_reg.get()
            d_reg.set(r_value)
            r_reg.set(d_value)
            return None

        if op == OP_JUMP:
            target = self.labels.get(instr.operand)
            if target is None:
                raise CpuError(f"undefined label {instr.operand}")
            self.pc = target
            return None

        if op == OP_COND_JUMP:
            if self.sign_flag:
                target = self.labels.get(instr.operand)
                if target is None:
                    raise CpuError(f"undefined label {instr.operand}")
                self.pc = target
            return None

        raise CpuError(f"unknown operator {op!r}")
