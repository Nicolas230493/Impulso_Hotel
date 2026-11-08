/* Gráficos de Impulso Hotel (Chart.js). Paleta categórica validada en orden fijo (nunca ciclada). */
const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const TINTA = "#52514e", GRILLA = "#e6e5e1";
const pesos = v => "$ " + Number(v).toLocaleString("es-AR", {maximumFractionDigits: 0});
Chart.defaults.font.family = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
Chart.defaults.color = TINTA;
Chart.defaults.plugins.tooltip.mode = "index";
Chart.defaults.plugins.tooltip.intersect = false;

function ejes(formato, horizontal) {
  const valor = {grid: {color: GRILLA}, border: {display: false}, ticks: {callback: formato}, beginAtZero: true};
  const cat = {grid: {display: false}, border: {color: GRILLA}};
  return horizontal ? {x: valor, y: cat} : {x: cat, y: valor};
}

function lineas(id, labels, series, formato, maxY) {
  const el = document.getElementById(id); if (!el) return;
  const opciones = {responsive: true, maintainAspectRatio: false, interaction: {mode: "index", intersect: false},
    plugins: {legend: {display: series.length > 1, position: "top", align: "start"},
              tooltip: {callbacks: {label: c => `${c.dataset.label}: ${c.parsed.y == null ? "—" : formato(c.parsed.y)}`}}},
    scales: ejes(formato)};
  if (maxY) opciones.scales.y.max = maxY;
  new Chart(el, {type: "line", data: {labels, datasets: series.map((s, i) => ({
    label: s.label, data: s.data, borderColor: SERIES[s.color ?? i], backgroundColor: SERIES[s.color ?? i],
    borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25, borderDash: s.dash || [], spanGaps: false}))},
    options: opciones});
}

function barras(id, labels, data, etiqueta, formato, horizontal) {
  const el = document.getElementById(id); if (!el) return;
  if (!data.length) { el.parentElement.innerHTML = '<p class="text-muted small">Sin datos en el período.</p>'; return; }
  new Chart(el, {type: "bar", data: {labels, datasets: [{label: etiqueta, data, backgroundColor: SERIES[0],
      borderRadius: 4, borderSkipped: "start", maxBarThickness: 28}]},
    options: {indexAxis: horizontal ? "y" : "x", responsive: true, maintainAspectRatio: false,
      plugins: {legend: {display: false}, tooltip: {callbacks: {label: c => formato(horizontal ? c.parsed.x : c.parsed.y)}}},
      scales: ejes(formato, horizontal)}});
}
