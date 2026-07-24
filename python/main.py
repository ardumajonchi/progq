# SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""Orchestrator: wires the Programma 101 emulation core to the arduino:web_ui Brick. Unlike a
turn-based game there's no AI/turn machinery here -- every key press synchronously advances the
Machine by one step and the updated state is broadcast back to the browser.

WebUI message protocol (event "key"):
  {"digit": "7"}                        -- key a digit/decimal point into the entry buffer
  {"operator": "add", "register": "B"}  -- execute one instruction now (register is optional;
                                            omitting it uses the entry buffer as the operand)
  {"clear_entry": true}                 -- clear the typed-but-not-committed entry buffer
  {"acknowledge_error": true}           -- the S key, pressed to clear a blocked/error state
  {"split": "B"} / {"unsplit": "B"}     -- split/unsplit one of B, C, D, E, F
  {"start_key": "V"}                    -- run the loaded program from that start key's label
  {"toggle_record": true}               -- enter/leave program-recording mode
  {"mark_label": 3}                     -- while recording, mark the current step as label 3
  {"commit_program": {"title": "..."}}  -- save the recorded buffer as a card and load it
  {"load_card": {"title": "..."}}       -- load a previously saved (or demo) card as the program
  {"delete_card": {"title": "..."}}     -- delete a saved card
  {"upload_card": {"text": "..."}}      -- parse a card from uploaded .txt content and save it
  {"clear_tape": true}                  -- clear the printer tape
  {"ai_operator": {"request": "..."}}   -- AI Operator: run a natural-language request as a
                                            sequence of real key presses (see agents.operator)
  {"ai_explain_error": true}            -- Assistant: explain the current blocked error
  {"ai_explain_card": {"title": "..."}} -- Assistant: explain what a saved card does
A saved card can be downloaded as a .txt file via GET /api/export_card?title=... (see
ProgramCard.to_text/from_text for the plain-text card format this round-trips through).
While `record_mode` is on, "operator"/"digit" keys append to the in-progress program instead of
executing immediately (interactive/calculator mode resumes once recording stops).
The "state" broadcast also carries `loaded_card_title`/`loaded_card_hint`: the bundled example
cards' logic assumes register values the card itself has no way to set (see engine.cards.
SETUP_HINTS), so the UI shows that one-line reminder the moment a card is loaded, before V/W/Y/Z
is pressed.

AI Operator and Assistant replies are pushed back over a separate "ai_reply" broadcast (not the
usual "state" broadcast) as {"kind": "operator"|"error"|"card", "text_or_log": ...}, since they
answer one request at a time rather than reflecting the machine's continuous state.
"""

from __future__ import annotations

import threading

from fastapi.responses import Response

from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import App

from agents.assistant import Assistant
from agents.operator import OperatorAgent
from cardstore import CardStore
from engine.cards import (
    CardError,
    ProgramCard,
    compound_interest_card,
    demo_countdown_card,
    fibonacci_card,
    moon_landing_card,
    pythagorean_card,
    setup_hint,
)
from engine.cpu import CpuError, Machine
from engine.instructions import Instruction, START_KEYS
from engine.printer import Tape
from hw import Hardware

_DB_NAME = "cards.db"


def public_state(
    machine: Machine,
    tape: Tape,
    record: dict,
    card_titles: list[str],
    ai_available: bool,
    loaded_card_title: str | None,
) -> dict:
    return {
        "registers": machine.registers.snapshot(),
        "entry": machine.entry,
        "blocked_error": machine.blocked_error,
        "tape": tape.lines[-200:],
        "record_mode": record["active"],
        "record_length": len(record["instructions"]),
        "record_labels": record["labels"],
        "card_titles": card_titles,
        "program_loaded": bool(machine.program),
        "ai_available": ai_available,
        "loaded_card_title": loaded_card_title,
        "loaded_card_hint": setup_hint(loaded_card_title),
    }


def main():
    machine = Machine()
    tape = Tape()
    record = {"active": False, "instructions": [], "labels": {}}
    loaded = {"title": None}

    card_store = CardStore(_DB_NAME)
    if not card_store.list_titles():
        for card_factory in (
            demo_countdown_card,
            fibonacci_card,
            compound_interest_card,
            pythagorean_card,
            moon_landing_card,
        ):
            card_store.save(card_factory())

    try:
        hw = Hardware()
        hw.play_startup()
        hw.show_idle()
    except Exception as exc:
        print(f"[progq] Hardware init failed, running without MCU/Bridge: {exc!r}")
        hw = None

    try:
        assistant = Assistant()
    except Exception as exc:
        print(f"[progq] Assistant init failed, running without AI explanations: {exc!r}")
        assistant = None

    # Guards every read/mutation of machine/tape/record: the AI Operator drives key presses from
    # a background thread (LLM inference is too slow to run on the socket handler thread), while a
    # human can keep clicking keys on the same socket handler thread at the same time.
    _state_lock = threading.Lock()

    def buzz(kind: str) -> None:
        if hw is None:
            return
        {"click": hw.play_click, "error": hw.play_error, "print": hw.play_print_chatter}[kind]()

    ui = WebUI()

    def broadcast_state() -> None:
        with _state_lock:
            snapshot = public_state(
                machine, tape, record, card_store.list_titles(), assistant is not None, loaded["title"]
            )
        ui.send_message("state", snapshot)

    def _handle_operator(operator: str, register: str | None) -> None:
        if record["active"]:
            record["instructions"].append(Instruction(operator=operator, register=register))
            tape.echo_key(operator, register)
            return
        tape.echo_key(operator, register)
        if hw is not None:
            hw.pulse_calculating()
        try:
            result = machine.press_key(operator, register)
        except CpuError:
            buzz("error")
            return
        buzz("click")
        if result is not None:
            tape.print_value(result, register)
            buzz("print")

    def _handle_digit(digit: str) -> None:
        if record["active"]:
            record["instructions"].append(Instruction(operator="digit", operand=digit))
            return
        try:
            machine.key_digit(digit)
        except ValueError:
            buzz("error")
            return
        buzz("click")

    def _handle_start_key(start_key: str) -> None:
        if start_key not in START_KEYS:
            return
        if hw is not None:
            hw.show_calculating()
        try:
            printed = machine.run_from(start_key)
        except CpuError:
            buzz("error")
            return
        finally:
            if hw is not None:
                hw.show_idle()
        for value in printed:
            tape.print_value(value)
        if printed:
            buzz("print")
        else:
            buzz("click")

    def _handle_commit_program(title: str) -> None:
        try:
            card = ProgramCard(title=title, instructions=list(record["instructions"]), labels=dict(record["labels"]))
        except CardError:
            buzz("error")
            return
        card_store.save(card)
        machine.load_program(card.instructions, card.labels)
        loaded["title"] = card.title
        record["active"] = False
        record["instructions"] = []
        record["labels"] = {}
        buzz("click")

    def _handle_load_card(title: str) -> None:
        card = card_store.load(title)
        if card is None:
            buzz("error")
            return
        machine.load_program(card.instructions, card.labels)
        loaded["title"] = card.title
        buzz("click")

    def _handle_upload_card(text: str) -> None:
        try:
            card = ProgramCard.from_text(text)
        except (CardError, ValueError):
            buzz("error")
            return
        card_store.save(card)
        buzz("click")

    def _apply_key(data: dict) -> None:
        """The original interactive-key dispatch, factored out so both a human's socket message
        and the AI Operator's tool calls (agents/operator.py) go through the identical, already-
        validated handlers above -- callers must hold _state_lock."""
        if "digit" in data:
            _handle_digit(str(data["digit"]))
        elif "operator" in data:
            _handle_operator(data["operator"], data.get("register"))
        elif data.get("clear_entry"):
            machine.clear_entry()
        elif data.get("acknowledge_error"):
            machine.acknowledge_error()
            buzz("click")
        elif "split" in data:
            machine.registers[data["split"]].split()
        elif "unsplit" in data:
            machine.registers[data["unsplit"]].unsplit()
        elif "start_key" in data:
            _handle_start_key(data["start_key"])
        elif "toggle_record" in data:
            record["active"] = not record["active"]
            if record["active"]:
                record["instructions"] = []
                record["labels"] = {}
        elif "mark_label" in data:
            if record["active"]:
                record["labels"][int(data["mark_label"])] = len(record["instructions"])
        elif "commit_program" in data:
            _handle_commit_program(data["commit_program"]["title"])
        elif "load_card" in data:
            _handle_load_card(data["load_card"]["title"])
        elif "delete_card" in data:
            card_store.delete(data["delete_card"]["title"])
            if loaded["title"] == data["delete_card"]["title"]:
                loaded["title"] = None
        elif "upload_card" in data:
            _handle_upload_card(data["upload_card"]["text"])
        elif data.get("clear_tape"):
            tape.clear()

    def _ai_key_press(action: dict) -> dict:
        """The callable OperatorAgent uses to press a key -- runs on the AI worker thread, so it
        takes _state_lock itself rather than relying on a caller. Broadcasts afterwards (outside
        the lock) so a human watching the panel sees each AI key press land live, same as their
        own clicks."""
        with _state_lock:
            _apply_key(action)
            registers = machine.registers.snapshot()
            observation = {
                "entry": machine.entry,
                "A": registers["A"],
                "blocked_error": machine.blocked_error,
                "last_tape_line": tape.lines[-1] if tape.lines else None,
            }
        broadcast_state()
        return observation

    try:
        operator_agent = OperatorAgent(_ai_key_press)
    except Exception as exc:
        print(f"[progq] AI Operator init failed, running without it: {exc!r}")
        operator_agent = None

    def _handle_ai_operator(request: str) -> None:
        request = request.strip()
        if not request:
            return
        if operator_agent is None:
            ui.send_message("ai_reply", {"kind": "operator", "log": ["AI Operator unavailable (LLM Brick not attached)."]})
            return

        def _run() -> None:
            log = operator_agent.run(request)
            ui.send_message("ai_reply", {"kind": "operator", "log": log})

        threading.Thread(target=_run, daemon=True).start()

    def _handle_ai_explain_error() -> None:
        if assistant is None:
            ui.send_message("ai_reply", {"kind": "error", "text": "AI Assistant unavailable (LLM Brick not attached)."})
            return
        with _state_lock:
            error = machine.blocked_error
            registers = machine.registers.snapshot()
            entry = machine.entry
        if error is None:
            ui.send_message("ai_reply", {"kind": "error", "text": "Nothing to explain -- no error is blocking the machine."})
            return

        def _run() -> None:
            try:
                text = assistant.explain_error(error, registers, entry)
            except Exception as exc:
                text = f"AI explanation failed: {exc!r}"
            ui.send_message("ai_reply", {"kind": "error", "text": text})

        threading.Thread(target=_run, daemon=True).start()

    def _handle_ai_explain_card(title: str) -> None:
        if assistant is None:
            ui.send_message("ai_reply", {"kind": "card", "title": title, "text": "AI Assistant unavailable (LLM Brick not attached)."})
            return
        card = card_store.load(title)
        if card is None:
            ui.send_message("ai_reply", {"kind": "card", "title": title, "text": "Card not found."})
            return
        instructions = [
            {"operator": i.operator, "register": i.register, "operand": i.operand} for i in card.instructions
        ]

        def _run() -> None:
            try:
                text = assistant.explain_card(title, instructions, card.labels)
            except Exception as exc:
                text = f"AI explanation failed: {exc!r}"
            ui.send_message("ai_reply", {"kind": "card", "title": title, "text": text})

        threading.Thread(target=_run, daemon=True).start()

    def _on_key(sid, data):
        data = data or {}
        if "ai_operator" in data:
            _handle_ai_operator(data["ai_operator"].get("request", ""))
            return
        if data.get("ai_explain_error"):
            _handle_ai_explain_error()
            return
        if "ai_explain_card" in data:
            _handle_ai_explain_card(data["ai_explain_card"]["title"])
            return

        with _state_lock:
            _apply_key(data)

        broadcast_state()

    def _on_connect(sid):
        broadcast_state()

    ui.on_connect(_on_connect)
    ui.on_message("key", _on_key)

    def _get_state() -> dict:
        with _state_lock:
            return public_state(
                machine, tape, record, card_store.list_titles(), assistant is not None, loaded["title"]
            )

    ui.expose_api("GET", "/api/state", _get_state)
    ui.expose_api("GET", "/api/tape", lambda: {"text": tape.as_text()})

    def _export_card(title: str):
        card = card_store.load(title)
        if card is None:
            return Response(status_code=404)
        return Response(
            content=card.to_text(),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{title}.txt"'},
        )

    ui.expose_api("GET", "/api/export_card", _export_card)

    App.run()


if __name__ == "__main__":
    main()
