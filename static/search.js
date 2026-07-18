// Toggle full/clamped abstract text.
document.addEventListener("click", function (e) {
  if (!e.target.classList.contains("abstract-toggle")) return;
  var abs = e.target.parentElement.querySelector(".en-abstract");
  if (!abs) return;
  var clamped = abs.classList.toggle("clamped");
  e.target.textContent = clamped ? "展开摘要" : "收起摘要";
});
