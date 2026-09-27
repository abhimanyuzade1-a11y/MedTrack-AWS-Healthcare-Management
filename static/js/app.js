"use strict";

document.addEventListener("submit", (event) => {
  const form = event.target;
  const confirmText = form.querySelector("[data-confirm]")?.dataset.confirm;
  if (confirmText && !window.confirm(confirmText)) {
    event.preventDefault();
    return;
  }
  if (form.matches("[data-disable-submit]")) {
    const button = form.querySelector("button[type='submit'], button:not([type])");
    if (button) {
      button.disabled = true;
      button.dataset.originalText = button.innerHTML;
      button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Sending request…';
    }
  }
});
