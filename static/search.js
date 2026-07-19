// Collapse the table of contents by default on narrow (mobile) screens.
(function () {
  var toc = document.querySelector(".toc-details");
  if (toc && window.matchMedia("(max-width: 760px)").matches) toc.removeAttribute("open");
})();

// Toggle full/clamped abstract text.
document.addEventListener("click", function (e) {
  if (!e.target.classList.contains("abstract-toggle")) return;
  var abs = e.target.parentElement.querySelector(".en-abstract");
  if (!abs) return;
  var clamped = abs.classList.toggle("clamped");
  e.target.textContent = clamped ? "展开摘要" : "收起摘要";
});
