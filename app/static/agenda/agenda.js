"use strict";

const buttons = [...document.querySelectorAll('[role="tab"]')];
const panels = [...document.querySelectorAll('[role="tabpanel"]')];

function selectDay(day, focus = false) {
  const target = buttons.find(button => button.dataset.day === day);
  if (!target) return;
  for (const button of buttons) {
    const selected = button === target;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  for (const panel of panels) panel.hidden = panel.dataset.daySection !== day;
  if (focus) target.focus({ preventScroll: true });
  history.replaceState(null, "", `#dia=${day}`);
}

buttons.forEach((button, index) => {
  button.addEventListener("click", () => selectDay(button.dataset.day));
  button.addEventListener("keydown", event => {
    let next;
    if (event.key === "ArrowRight") next = (index + 1) % buttons.length;
    if (event.key === "ArrowLeft") next = (index + buttons.length - 1) % buttons.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = buttons.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    selectDay(buttons[next].dataset.day, true);
  });
});

const savedDay = new URLSearchParams(location.hash.slice(1)).get("dia");
if (savedDay) selectDay(savedDay);

document.getElementById("refresh")?.addEventListener("click", event => {
  const button = event.currentTarget;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  location.reload();
});
