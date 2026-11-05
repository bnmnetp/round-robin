// Small progressive enhancements. Every page works without this file.
(function () {
  "use strict";

  function clamp(input, value) {
    const min = Number(input.dataset.min ?? -Infinity);
    const max = Number(input.dataset.max ?? Infinity);
    return Math.min(max, Math.max(min, value));
  }

  function changed(input) {
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;

    // −/+ steppers and the "11" button
    if (button.dataset.target) {
      const input = document.getElementById(button.dataset.target);
      if (!input) return;
      if (button.dataset.set !== undefined) {
        input.value = button.dataset.set;
      } else {
        const current = parseInt(input.value, 10);
        const step = Number(button.dataset.step);
        // An empty score field starts from 0 on "+".
        const start = Number.isNaN(current) ? (step > 0 ? 0 : 1) : current;
        input.value = clamp(input, start + step);
      }
      changed(input);
      return;
    }

    // select all / none
    if (button.dataset.check) {
      const on = button.dataset.value === "1";
      document
        .querySelectorAll(button.dataset.check + " input[type=checkbox]")
        .forEach((box) => {
          // "All" means all that are showing through the filter.
          if (!on || !box.closest("[hidden]")) box.checked = on;
        });
      updateSummary();
      return;
    }

    // copy a link
    if (button.dataset.copy) {
      const field = document.querySelector(button.dataset.copy);
      if (!field) return;
      const done = () => {
        const label = button.textContent;
        button.textContent = "Copied";
        setTimeout(() => (button.textContent = label), 1500);
      };
      if (navigator.clipboard) {
        navigator.clipboard.writeText(field.value).then(done, () => field.select());
      } else {
        field.select();
      }
    }
  });

  // filter boxes: <input data-filter="#list li"> hides items whose data-name
  // doesn't contain the text
  document.querySelectorAll("[data-filter]").forEach((box) => {
    box.addEventListener("input", () => {
      const q = box.value.trim().toLowerCase();
      document.querySelectorAll(box.dataset.filter).forEach((item) => {
        if (item.dataset.name === undefined) return;
        item.hidden = q !== "" && !item.dataset.name.includes(q);
      });
    });
  });

  // confirm before destructive actions; disable submit buttons so a slow
  // connection doesn't send a score twice
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
      return;
    }
    const button = form.querySelector("button:not([type=button])");
    if (button) {
      setTimeout(() => {
        button.disabled = true;
        if (form.dataset.busy) button.textContent = form.dataset.busy;
      }, 0);
    }
  });

  // pages restored from the back/forward cache keep disabled buttons
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      document.querySelectorAll("form button[disabled]").forEach((b) => (b.disabled = false));
    }
  });

  // ---- new tournament: live summary

  const form = document.getElementById("new-tournament");
  function updateSummary() {
    if (!form) return;
    const out = document.getElementById("summary");
    const submit = document.getElementById("make-schedule");
    const n = form.querySelectorAll("input[name=players]:checked").length;
    const courts = parseInt(form.elements.courts.value, 10) || 0;
    const rounds = parseInt(form.elements.rounds.value, 10) || 0;
    const seats = 4 * Math.min(courts, Math.floor(n / 4));
    const sit = n - seats;

    if (n < 4 || courts < 1 || rounds < 1) {
      out.textContent = `${n} picked. Pick at least 4 players.`;
      submit.disabled = n < 4;
      return;
    }
    submit.disabled = false;
    const used = seats / 4;
    let text = `${n} players · ${used} court${used === 1 ? "" : "s"}`;
    if (used < courts) text += ` (only ${used} of ${courts} needed)`;
    text += ` · ${rounds} round${rounds === 1 ? "" : "s"}. `;
    text += sit
      ? `${sit} sit${sit === 1 ? "s" : ""} out each round; ranked by average points per game.`
      : "Everyone plays every round; ranked by total points.";
    out.textContent = text;

    // Same test as scheduler.partner_repeats_unavoidable.
    const mostGames = rounds - Math.floor((sit * rounds) / n);
    if (mostGames > n - 1 || (seats / 2) * rounds > (n * (n - 1)) / 2) {
      const warn = document.createElement("span");
      warn.className = "warn";
      warn.textContent = "Some partners will have to repeat. Fewer rounds avoids that.";
      out.appendChild(warn);
    }
  }
  if (form) {
    form.addEventListener("input", updateSummary);
    form.addEventListener("change", updateSummary);
    form.addEventListener("submit", () => {
      document.getElementById("summary").textContent = "Making the schedule…";
    });
    updateSummary();
  }

  // ---- highlight a player (remembered per tournament on this device)

  document.querySelectorAll("select[data-highlight]").forEach((select) => {
    const key = "rr-highlight-" + select.dataset.highlight;
    function apply() {
      document.querySelectorAll("[data-pid].me").forEach((el) => el.classList.remove("me"));
      if (select.value) {
        document
          .querySelectorAll(`[data-pid="${CSS.escape(select.value)}"]`)
          .forEach((el) => el.classList.add("me"));
      }
    }
    try {
      const saved = localStorage.getItem(key);
      if (saved && select.querySelector(`option[value="${CSS.escape(saved)}"]`)) {
        select.value = saved;
      }
    } catch (e) {
      /* storage unavailable: just don't remember */
    }
    select.addEventListener("change", () => {
      try {
        localStorage.setItem(key, select.value);
      } catch (e) {
        /* ignore */
      }
      apply();
    });
    apply();
  });
})();
