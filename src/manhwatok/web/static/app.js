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
    if (!slide) return;
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
})();
