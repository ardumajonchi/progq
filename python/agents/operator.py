# SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""AI Operator agent: turns a natural-language request into a sequence of real key presses, using
the official arduino:llm Brick's tool-calling to drive the *exact same* validated key handlers
`main.py` exposes to a human's browser clicks -- the LLM is never in the calculation path, it is
only ever "another hand on the keyboard". Every action it takes still goes through Machine's real
register/capacity/blocking-condition checks (engine.cpu.Machine, via main.py's dispatcher), so a
bad generation can only press a wrong key -- exactly as recoverable as a human mistyping -- never
produce a wrong answer that bypasses the emulation core.

Since a request may take several key presses to satisfy (type digits, press an operator, read the
result, decide the next key), and the Brick's tool-calling invokes at most one tool per `chat()`
call (mirroring conquest-q's Leader agent), `OperatorAgent.run()` drives its own call/observe loop
here rather than relying on the Brick to do multi-step planning internally.
"""

from __future__ import annotations

from arduino.app_bricks.llm import LargeLanguageModel, tool

_SYSTEM_PROMPT = (
    "You are the on-screen AI Operator for an emulated Olivetti Programma 101, a 1965 "
    "programmable desktop calculator. You do not compute results yourself -- you only press keys "
    "on the real machine's keyboard, one at a time, exactly like a human operator would, and you "
    "are told what changed after every key so you can decide the next one. The accumulator is "
    "always register A; every arithmetic key operates against it. Type a number by pressing "
    "key_digit once per character, then press an operator key to act on it. Pass a register name "
    "to press_operator to use that register's value as the operand instead of what you just "
    "typed. Call press_done as soon as you've printed the answer the user asked for, or if you "
    "get stuck after a few tries -- never loop forever."
)

_OPERATORS = (
    "add",
    "sub",
    "mul",
    "div",
    "sqrt",
    "transfer_to_m",
    "exchange_a",
    "decimal_part",
    "clear",
    "print",
    "stop",
)

_MAX_STEPS = 12


class OperatorAgent:
    """One instance per running emulator. `key_press` is a callable `(action: dict) -> dict`
    supplied by main.py, wrapping the same handlers a browser key click uses, and returning a
    compact snapshot (entry buffer, A, last tape line, blocked error) after each action -- this
    agent never touches Machine/Tape/CardStore directly, only through that callable."""

    def __init__(self, key_press, model: str | None = None):
        self._key_press = key_press
        self._done = False
        self._log: list[str] = []

        @tool
        def key_digit(digit: str) -> str:
            """Type one digit or a decimal point into the entry buffer, like pressing a numeric
            key. Call once per digit for multi-digit numbers.

            Args:
                digit: a single character, "0"-"9" or ".".
            """
            return self._dispatch({"digit": digit})

        @tool
        def press_operator(operator: str, register: str = "") -> str:
            """Press one operator key. Executes immediately against the accumulator (A).

            Args:
                operator: one of "add", "sub", "mul", "div", "sqrt", "transfer_to_m",
                    "exchange_a", "decimal_part", "clear", "print", "stop".
                register: optional register to use as the operand instead of the typed entry
                    buffer -- one of "M", "R", "B", "C", "D", "E", "F". Leave empty to use the
                    entry buffer.
            """
            if operator not in _OPERATORS:
                return f"Unknown operator {operator!r}; must be one of {_OPERATORS}."
            return self._dispatch({"operator": operator, "register": register or None})

        @tool
        def acknowledge_error() -> str:
            """Press S to clear a blocked error state (division by zero, negative square root,
            or register overflow) so keys work again."""
            return self._dispatch({"acknowledge_error": True})

        @tool
        def run_program(start_key: str) -> str:
            """Run the currently loaded program card from one of its start labels.

            Args:
                start_key: one of "V", "W", "Y", "Z".
            """
            return self._dispatch({"start_key": start_key})

        @tool
        def press_done(summary: str) -> str:
            """Call this once you've finished the requested task (e.g. printed the answer).

            Args:
                summary: a short (1 sentence) summary of what you did, for the user to read.
            """
            self._done = True
            self._log.append(f"done: {summary}")
            return "Done."

        self.llm = LargeLanguageModel(
            system_prompt=_SYSTEM_PROMPT,
            tools=[key_digit, press_operator, acknowledge_error, run_program, press_done],
            max_tokens=200,
            model=model,
        )

    def _dispatch(self, action: dict) -> str:
        observation = self._key_press(action)
        self._log.append(f"{action} -> {observation}")
        return str(observation)

    def run(self, request: str) -> list[str]:
        """Drive the agent from a natural-language request until it calls press_done or runs out
        of steps. Returns the full tool-call/observation trace for display in the UI."""
        self._done = False
        self._log = []
        prompt = request
        for _ in range(_MAX_STEPS):
            try:
                self.llm.chat(prompt)
            except Exception as exc:
                self._log.append(f"[error] {exc!r}")
                break
            if self._done:
                break
            prompt = "Continue. What is the next key to press?"
        else:
            self._log.append("[stopped: reached max step count without press_done]")
        return list(self._log)
