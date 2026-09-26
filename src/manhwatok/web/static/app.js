// manhwatok web: live updates, toasts, the slide lightbox. htmx does everything else.
(() => {
  const body = document.body;

  // One event stream per tab; each event becomes a DOM event on <body> that htmx
  // attributes can listen to (hx-trigger="changed-posts from:body").
  const source = new EventSource("/events");
  source.addEventListener("changed", (e) => {
    htmx.trigger(body, "changed-" + JSON.parse(e.data).what);
  });
  for (const kind of ["job", "log", "question", "answered"]) {
    source.addEventListener(kind, (e) => htmx.trigger(body, kind, JSON.parse(e.data)));
  }

  // Toasts: from HX-Trigger {"notice": {...}} and from finished jobs.
  const toasts = document.getElementById("toasts");
  function toast(text, level) {
    const div = document.createElement("div");
    div.className = "toast " + (level || "info");
    div.textContent = text;
    toasts.append(div);
    setTimeout(() => div.remove(), level === "error" ? 10000 : 5000);
  }
  body.addEventListener("notice", (e) => toast(e.detail.text, e.detail.level));
  body.addEventListener("job", (e) => {
    if (e.detail.state === "finished") toast(e.detail.outcome, e.detail.failed ? "error" : "info");
  });

  // The post the detail pane shows (from the URL), for the table to keep its row marked;
  // a click on a post marks its row at once.
  window.selectedPost = () => new URLSearchParams(location.search).get("post") || "";
  document.addEventListener("click", (e) => {
    const opener = e.target.closest("#posts-table .card .open");
    if (!opener) return;
    document.querySelectorAll("#posts-table .card.is-selected").forEach((c) => c.classList.remove("is-selected"));
    opener.closest(".card").classList.add("is-selected");
  });

  // Viewer: a filmstrip click puts that slide on the stage; the stage opens the lightbox on it.
  document.addEventListener("click", (e) => {
    const thumb = e.target.closest(".filmstrip [data-slide]");
    if (!thumb || !e.isTrusted) return;
    e.stopPropagation();
    const viewer = thumb.closest(".viewer");
    const stage = viewer.querySelector("#stage");
    stage.src = thumb.src;
    stage.dataset.full = thumb.src;
    viewer.querySelectorAll("[data-slide]").forEach((t) => t.setAttribute("aria-current", t === thumb ? "true" : "false"));
  }, true);
  document.addEventListener("click", (e) => {
    const stage = e.target.closest(".viewer .stage");
    if (!stage) return;
    const current = stage.closest(".viewer").querySelector('[data-slide][aria-current="true"]');
    if (current) current.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });

  // Lightbox: click a [data-slide] image; ← → step through its [data-gallery].
  const box = document.getElementById("lightbox");
  const big = box.querySelector("img");
  let slides = [];
  let at = 0;
  function show(n) {
    at = (n + slides.length) % slides.length;
    big.src = slides[at].dataset.full || slides[at].src;
  }
  document.addEventListener("click", (e) => {
    const slide = e.target.closest("[data-slide]");
    if (!slide || (e.isTrusted && slide.closest(".filmstrip"))) return;
    slides = [...slide.closest("[data-gallery]").querySelectorAll("[data-slide]")];
    show(slides.indexOf(slide));
    box.showModal();
  });
  box.querySelector(".prev").addEventListener("click", () => show(at - 1));
  box.querySelector(".next").addEventListener("click", () => show(at + 1));
  box.querySelector(".close").addEventListener("click", () => box.close());
  box.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") show(at - 1);
    if (e.key === "ArrowRight") show(at + 1);
  });

  // New post: the theme fills the title unless one was typed.
  document.addEventListener("change", (e) => {
    if (e.target.id !== "theme") return;
    const title = document.getElementById("title");
    const themed = e.target.selectedOptions[0].dataset.title;
    if (title && themed && !title.value) title.value = themed;
  });

  // New post: click a candidate to pick or drop it; the picks list follows.
  function toggle(card) {
    const list = document.getElementById("picks");
    const id = card.dataset.id;
    const picked = card.getAttribute("aria-pressed") === "true";
    if (picked) {
      list.querySelector(`.pick[data-id="${id}"]`)?.remove();
      card.setAttribute("aria-pressed", "false");
    } else {
      const template = card.querySelector("template");
      list.append(template.content.firstElementChild.cloneNode(true));
      card.setAttribute("aria-pressed", "true");
    }
    ranks();
  }
  function ranks() {
    const order = [...document.querySelectorAll("#picks .pick")].map((li) => li.dataset.id);
    document.querySelectorAll("#candidates .candidate").forEach((card) => {
      card.querySelector(".rank").textContent = order.indexOf(card.dataset.id) + 1 || "";
    });
  }
  document.addEventListener("click", (e) => {
    const card = e.target.closest("#candidates .candidate");
    if (card) return toggle(card);
    const move = e.target.closest("#picks [data-move]");
    if (!move) return;
    const li = move.closest(".pick");
    if (move.dataset.move === "up" && li.previousElementSibling) li.previousElementSibling.before(li);
    if (move.dataset.move === "down" && li.nextElementSibling) li.nextElementSibling.after(li);
    ranks();
  });
  document.addEventListener("keydown", (e) => {
    const card = e.target.closest?.("#candidates .candidate");
    if (card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggle(card); }
  });
  // Drag a pick to reorder.
  let dragged = null;
  document.addEventListener("dragstart", (e) => {
    dragged = e.target.closest?.("#picks .pick");
    if (dragged) dragged.classList.add("dragging");
  });
  document.addEventListener("dragend", () => { dragged?.classList.remove("dragging"); dragged = null; ranks(); });
  document.addEventListener("dragover", (e) => {
    const over = e.target.closest?.("#picks .pick");
    if (!dragged || !over || over === dragged) return;
    e.preventDefault();
    const box = over.getBoundingClientRect();
    if (e.clientY < box.top + box.height / 2) over.before(dragged); else over.after(dragged);
  });
  document.body.addEventListener("htmx:afterSwap", (e) => { if (e.detail.target.id === "results") ranks(); });
})();
