// Interaction for the daily-review reading page: TOC drawer, abstract fold.
(function () {
  var drawer = document.querySelector("[data-drawer]");

  function setDrawer(open) {
    if (!drawer) return;
    drawer.classList.toggle("open", open);
    var tab = drawer.querySelector(".toc-tab");
    var panel = drawer.querySelector(".toc-panel");
    var arrow = drawer.querySelector(".toc-arrow");
    if (panel) panel.hidden = !open;
    if (tab) tab.setAttribute("aria-expanded", open ? "true" : "false");
    if (arrow) arrow.textContent = open ? "‹" : "›";
  }

  document.addEventListener("click", function (e) {
    // TOC drawer open/close (tab + × share [data-drawer-toggle])
    if (e.target.closest("[data-drawer-toggle]")) {
      setDrawer(!(drawer && drawer.classList.contains("open")));
      return;
    }
    // clicking a TOC entry jumps and closes the drawer
    if (e.target.closest(".toc-panel a")) {
      setDrawer(false);
      return;
    }
    // abstract expand / collapse
    var toggle = e.target.closest(".abstract-toggle");
    if (toggle) {
      var wrap = toggle.closest(".abstract-wrap");
      var abs = wrap && wrap.querySelector(".abstract");
      if (!abs) return;
      var clamped = abs.classList.toggle("clamped");
      toggle.textContent = clamped ? "展开 ▾" : "收起 ▴";
    }
  });

  // Hide the "展开" affordance for abstracts that fit within 3 lines (nothing to expand).
  function pruneToggles() {
    var wraps = document.querySelectorAll(".abstract-wrap");
    for (var i = 0; i < wraps.length; i++) {
      var abs = wraps[i].querySelector(".abstract.clamped");
      var btn = wraps[i].querySelector(".abstract-toggle");
      if (abs && btn && abs.scrollHeight <= abs.clientHeight + 2) {
        btn.style.display = "none";
      }
    }
  }
  if (document.readyState !== "loading") pruneToggles();
  else document.addEventListener("DOMContentLoaded", pruneToggles);
})();
