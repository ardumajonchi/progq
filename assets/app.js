// SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
//
// SPDX-License-Identifier: MPL-2.0
//
// Programma 101 emulator UI — every key is a click target sending a small action payload over
// the WebUI socket; the server always answers with a full "state" broadcast (see python/main.py's
// docstring for the exact "key" message protocol this file implements).

let socket;
let latestState = null;
let splitRegisters = new Set(); // client-side toggle memory for which registers are split
let pendingRegister = null; // register selected via a reg-key, consumed by the next operator key

function sendKey(payload) {
  socket.emit("key", payload);
}

function renderTape(lines) {
  const tape = document.getElementById("tape");
  const wasAtBottom = tape.scrollTop + tape.clientHeight >= tape.scrollHeight - 4;
  tape.innerHTML = "";
  for (const line of lines) {
    const div = document.createElement("div");
    div.className = "tape-line";
    div.textContent = line;
    tape.appendChild(div);
  }
  if (wasAtBottom) tape.scrollTop = tape.scrollHeight;
}

function registerText(reg) {
  if (!reg) return "0";
  if (reg.split) return `${reg.upper}|${reg.lower}`;
  return reg.value;
}

function renderReadouts(state) {
  document.getElementById("entry-display").textContent = state.entry || "0";
  document.getElementById("a-display").textContent = registerText(state.registers.A);
  document.getElementById("m-display").textContent = registerText(state.registers.M);
  document.getElementById("r-display").textContent = registerText(state.registers.R);
  document.getElementById("error-display").textContent = state.blocked_error || "";
}

function renderRecording(state) {
  const status = document.getElementById("record-status");
  const recBtn = document.getElementById("rec-btn");
  status.classList.toggle("active", state.record_mode);
  recBtn.classList.toggle("active", state.record_mode);
  status.textContent = state.record_mode
    ? `recording -- ${state.record_length} step(s)`
    : "not recording";
  document.getElementById("step-num").textContent = state.record_mode
    ? state.record_length
    : 0;
}

function renderCards(state) {
  const list = document.getElementById("card-list");
  list.innerHTML = "";
  for (const title of state.card_titles) {
    const li = document.createElement("li");
    const span = document.createElement("span");
    span.className = "card-title";
    span.textContent = title;
    span.addEventListener("click", () => sendKey({ load_card: { title } }));
    const dl = document.createElement("a");
    dl.className = "card-dl";
    dl.textContent = "⬇";
    dl.title = "Download as .txt";
    dl.href = `/api/export_card?title=${encodeURIComponent(title)}`;
    dl.addEventListener("click", (evt) => evt.stopPropagation());
    const del = document.createElement("button");
    del.className = "card-del";
    del.textContent = "✕";
    del.addEventListener("click", (evt) => {
      evt.stopPropagation();
      sendKey({ delete_card: { title } });
    });
    li.appendChild(span);
    li.appendChild(dl);
    li.appendChild(del);
    list.appendChild(li);
  }
}

function onState(payload) {
  latestState = payload;
  renderTape(latestState.tape);
  renderReadouts(latestState);
  renderRecording(latestState);
  renderCards(latestState);
}

function setupKeypad() {
  for (const el of document.querySelectorAll(".numkey")) {
    el.addEventListener("click", () => sendKey({ digit: el.dataset.digit }));
  }
}

// Register-then-operator flow: pressing a reg-key selects (and highlights) it as the operand for
// whichever operator key is pressed next; pressing an operator with nothing selected uses the
// entry buffer as the operand instead (per the "key" protocol's optional `register` field).
function setupOps() {
  for (const el of document.querySelectorAll(".opkey")) {
    el.addEventListener("click", () => {
      sendKey({ operator: el.dataset.op, register: pendingRegister || undefined });
      clearPendingRegister();
    });
  }
  document.getElementById("s-key").addEventListener("click", () => {
    if (latestState && latestState.blocked_error) {
      sendKey({ acknowledge_error: true });
    } else {
      sendKey({ operator: "stop" });
    }
  });
}

function clearPendingRegister() {
  pendingRegister = null;
  for (const el of document.querySelectorAll(".reg-key")) el.classList.remove("active");
}

function setupRegisterKeys() {
  for (const el of document.querySelectorAll(".reg-key")) {
    el.addEventListener("click", () => {
      const reg = el.dataset.reg;
      if (pendingRegister === reg) {
        clearPendingRegister();
        return;
      }
      clearPendingRegister();
      pendingRegister = reg;
      el.classList.add("active");
    });
  }
}

function setupSplit() {
  document.getElementById("split-btn").addEventListener("click", () => {
    const reg = prompt("Split/unsplit which register? (B, C, D, E, F)");
    if (!reg) return;
    const name = reg.trim().toUpperCase();
    if (!"BCDEF".includes(name)) return;
    if (splitRegisters.has(name)) {
      splitRegisters.delete(name);
      sendKey({ unsplit: name });
    } else {
      splitRegisters.add(name);
      sendKey({ split: name });
    }
  });
}

function setupStartKeys() {
  for (const el of document.querySelectorAll(".start-key")) {
    el.addEventListener("click", () => sendKey({ start_key: el.dataset.start }));
  }
}

function setupModeBar() {
  document.getElementById("rec-btn").addEventListener("click", () => sendKey({ toggle_record: true }));
  document.getElementById("clr-ent-btn").addEventListener("click", () => sendKey({ clear_entry: true }));
  document.getElementById("clr-tape-btn").addEventListener("click", () => sendKey({ clear_tape: true }));
  document.getElementById("share-tape-btn").addEventListener("click", shareTape);
}

async function shareTape() {
  const res = await fetch("/api/tape");
  const { text } = await res.json();
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "programma-q-tape.txt";
  a.click();
  URL.revokeObjectURL(url);
}

function setupLabels() {
  for (const el of document.querySelectorAll(".label-key")) {
    el.addEventListener("click", () => sendKey({ mark_label: Number(el.dataset.label) }));
  }
}

function setupCommit() {
  document.getElementById("commit-btn").addEventListener("click", () => {
    const input = document.getElementById("commit-title");
    const title = input.value.trim();
    if (!title) return;
    sendKey({ commit_program: { title } });
    input.value = "";
  });
}

function setupUpload() {
  const input = document.getElementById("card-upload");
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    const text = await file.text();
    sendKey({ upload_card: { text } });
    input.value = "";
  });
}

function main() {
  setupKeypad();
  setupOps();
  setupRegisterKeys();
  setupSplit();
  setupStartKeys();
  setupModeBar();
  setupLabels();
  setupCommit();
  setupUpload();

  socket = io();
  socket.on("state", onState);
}

main();
