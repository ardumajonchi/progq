# SPDX-FileCopyrightText: Copyright (C) Programma 101 Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""Instruction model: one P101 program step is a (register, operator) pair, matching how the real
machine encodes a single card byte (left nibble selects the register/type, right nibble selects
the operator or a literal digit). This module is a clean-room definition against the machine's
documented instruction set -- it defines the operator vocabulary and the physical key symbol table,
not a translation of any existing emulator's source.
"""

from __future__ import annotations

from dataclasses import dataclass

# Arithmetic / register operators, keyed by the machine's own symbol.
OP_ADD = "add"  # +
OP_SUB = "sub"  # -
OP_MUL = "mul"  # x
OP_DIV = "div"  # :  (displayed as ÷)
OP_SQRT = "sqrt"  # sqrt
OP_TRANSFER_TO_M = "transfer_to_m"  # A-down: register -> M
OP_EXCHANGE_A = "exchange_a"  # A-hat: exchange register <-> A
OP_DECIMAL_PART = "decimal_part"  # extract the fractional part of a register
OP_CLEAR = "clear"  # *  clear a register
OP_PRINT = "print"  # diamond  print a register to tape
OP_STOP = "stop"  # S
OP_RS = "rs"  # RS  exchange D <-> R
OP_JUMP = "jump"  # unconditional jump to a label
OP_COND_JUMP = "cond_jump"  # jump to a label if the last comparison/sign flag is set
OP_DIGIT = "digit"  # a literal digit (0-9) or '.' keyed into the entry buffer

ARITHMETIC_OPS = (OP_ADD, OP_SUB, OP_MUL, OP_DIV)
UNARY_OPS = (OP_SQRT, OP_DECIMAL_PART)

# Physical/EMU101 key symbol -> internal operator code.
KEY_SYMBOLS = {
    "+": OP_ADD,
    "-": OP_SUB,
    "x": OP_MUL,
    ":": OP_DIV,
    "sqrt": OP_SQRT,
    "A_down": OP_TRANSFER_TO_M,
    "A_hat": OP_EXCHANGE_A,
    "decimal_part": OP_DECIMAL_PART,
    "clear": OP_CLEAR,
    "print": OP_PRINT,
    "S": OP_STOP,
    "RS": OP_RS,
}

# The four start keys map to the first four of the machine's 32 addressable labels.
START_KEYS = {"V": 1, "W": 2, "Y": 3, "Z": 4}

MAX_LABEL = 32


@dataclass(frozen=True)
class Instruction:
    """One program step. `register` names the operand register (None for stop/jump/digit-only
    steps). `operand` carries a literal digit/label number where the operator needs one (e.g.
    OP_DIGIT's digit character, OP_JUMP/OP_COND_JUMP's target label)."""

    operator: str
    register: str | None = None
    operand: str | int | None = None

    def __post_init__(self) -> None:
        if self.operator in (OP_JUMP, OP_COND_JUMP):
            if not isinstance(self.operand, int) or not (1 <= self.operand <= MAX_LABEL):
                raise ValueError(f"{self.operator} requires a label operand in 1..{MAX_LABEL}")
        if self.operator == OP_DIGIT:
            if not isinstance(self.operand, str) or self.operand not in "0123456789.":
                raise ValueError("OP_DIGIT requires a single digit or '.' operand")
