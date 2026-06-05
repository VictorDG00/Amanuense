/* Amanuense — Vade Mecum do Futuro
   Vanilla JS + D3.js v7 */

"use strict";

// ── State ──────────────────────────────────────────────────────────────────────
const state = {
  graph: null,
  vigency: null,
  corpusTexts: null,
  diffLog: null,
  simulation: null,
  svg: null,
  zoomBehavior: null,
  selectedNodeId: null,
  filters: {
    nodeType: "all",
    status: "all",
    edgeType: "all",
    implicit: "all",
    minWeight: 0,
  },
  currentView: "graph",
  tourIndex: 0,
  tourStepIndex: 0,
  highlightedNodes: new Set(),
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $  = (id) => document.getElementById(id);
const $q = (sel) => document.querySelector(sel);

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  // Load data from global variables injected by graph-data.js / vigency-data.js
  if (typeof window.GRAPH_DATA === "undefined") {
    showError("Nenhum grafo encontrado. Execute <code>amanuense run</code> primeiro para gerar os dados.");
    return;
  }

  state.graph = window.GRAPH_DATA;
  state.vigency = typeof window.VIGENCY_DATA !== "undefined" ? window.VIGENCY_DATA : null;

  // Try to load corpus-texts and diff-log via fetch (optional)
  try {
    const ctResp = await fetch("../output/corpus-texts.json");
    if (ctResp.ok) state.corpusTexts = await ctResp.json();
  } catch (_) {}
  try {
    const dlResp = await fetch("../output/diff-log.json");
    if (dlResp.ok) state.diffLog = await dlResp.json();
  } catch (_) {}

  hideLoading();
  populateSidebar();
  renderGraph();
  populateRoleSelect();
  populateHierarchyView();
  populateTimelineView();
  populateTourView();
  bindEvents();
}

function showError(msg) {
  $("loading").innerHTML = `
    <h2>Amanuense</h2>
    <p style="color:#e74c3c;max-width:400px;text-align:center;">${msg}</p>
    <p style="margin-top:16px;font-size:13px;opacity:0.5">Ver README para instruções de uso</p>
  `;
}

function hideLoading() {
  $("loading").classList.add("hidden");
}

// ── Sidebar Stats ──────────────────────────────────────────────────────────────
function populateSidebar() {
  const g = state.graph;
  const nodeCount = g.nodes.length;
  const edgeCount = g.links.length;
  const vigentCount = g.nodes.filter(n => n.status === "vigente").length;
  const revogadoCount = g.nodes.filter(n => n.status === "revogado").length;

  $("stats-bar").innerHTML = `
    <span>Nós: <b>${nodeCount}</b></span>
    <span>Arestas: <b>${edgeCount}</b></span>
    <span>Vigentes: <b style="color:#27ae60">${vigentCount}</b></span>
    <span>Revogados: <b style="color:#e74c3c">${revogadoCount}</b></span>
  `;

  // Populate filter dropdowns
  const nodeTypes = [...new Set(g.nodes.map(n => n.type))].sort();
  const nodeTypeSelect = $("filter-node-type");
  nodeTypes.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t; opt.textContent = t;
    nodeTypeSelect.appendChild(opt);
  });

  const edgeTypes = [...new Set(g.links.map(e => e.type))].sort();
  const edgeTypeSelect = $("filter-edge-type");
  edgeTypes.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t; opt.textContent = t;
    edgeTypeSelect.appendChild(opt);
  });
}

// ── D3 Graph ──────────────────────────────────────────────────────────────────
function getFilteredData() {
  const f = state.filters;
  const g = state.graph;

  let nodes = g.nodes.filter(n => {
    if (f.nodeType !== "all" && n.type !== f.nodeType) return false;
    if (f.status !== "all" && n.status !== f.status) return false;
    return true;
  });
  const nodeIds = new Set(nodes.map(n => n.id));

  let links = g.links.filter(e => {
    if (!nodeIds.has(e.source) && !nodeIds.has(e.source?.id)) return false;
    if (!nodeIds.has(e.target) && !nodeIds.has(e.target?.id)) return false;
    if (f.edgeType !== "all" && e.type !== f.edgeType) return false;
    if (f.implicit !== "all" && String(e.implicit) !== f.implicit) return false;
    if (e.weight < f.minWeight) return false;
    return true;
  });

  return { nodes: nodes.map(n => ({ ...n })), links: links.map(e => ({ ...e })) };
}

function renderGraph() {
  const canvas = $("graph-canvas");
  canvas.innerHTML = "";
  const W = canvas.clientWidth || 900;
  const H = canvas.clientHeight || 600;

  const { nodes, links } = getFilteredData();
  if (nodes.length === 0) return;

  const svg = d3.select(canvas)
    .append("svg")
    .attr("width", "100%")
    .attr("height", "100%")
    .attr("viewBox", `0 0 ${W} ${H}`);

  state.svg = svg;

  // Arrow markers per color
  const defs = svg.append("defs");
  const arrowColors = [...new Set(links.map(e => e.color || "#999"))];
  arrowColors.forEach(color => {
    const safeId = "arrow-" + color.replace("#", "");
    defs.append("marker")
      .attr("id", safeId)
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 18).attr("refY", 0)
      .attr("markerWidth", 6).attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", color);
  });

  const zoom = d3.zoom()
    .scaleExtent([0.1, 4])
    .on("zoom", (event) => g_container.attr("transform", event.transform));
  svg.call(zoom);
  state.zoomBehavior = zoom;

  const g_container = svg.append("g");

  const simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id(d => d.id).distance(d => 80 + (1 - d.weight) * 60))
    .force("charge", d3.forceManyBody().strength(-200))
    .force("center", d3.forceCenter(W / 2, H / 2))
    .force("collide", d3.forceCollide(20));
  state.simulation = simulation;

  // Links
  const link = g_container.append("g")
    .selectAll("line")
    .data(links)
    .join("line")
    .attr("stroke", d => d.color || "#999")
    .attr("stroke-width", d => 1 + d.weight * 2)
    .attr("stroke-dasharray", d => d.implicit ? "5,3" : null)
    .attr("stroke-opacity", d => d.stale ? 0.3 : 0.7)
    .attr("marker-end", d => `url(#arrow-${(d.color || "#999").replace("#", "")})`)
    .on("mouseenter", (event, d) => showEdgeTooltip(event, d))
    .on("mouseleave", hideTooltip);

  // Nodes
  const nodeRadius = d => {
    if (d.type === "norma") return 16;
    if (d.type === "artigo") return 9;
    if (d.type === "papel" || d.type === "entidade") return 12;
    return 6;
  };

  const node = g_container.append("g")
    .selectAll("g")
    .data(nodes)
    .join("g")
    .attr("class", "node-group")
    .call(d3.drag()
      .on("start", dragStarted)
      .on("drag", dragged)
      .on("end", dragEnded))
    .on("click", (event, d) => { event.stopPropagation(); selectNode(d.id); })
    .on("mouseenter", (event, d) => showNodeTooltip(event, d))
    .on("mouseleave", hideTooltip);

  node.append("circle")
    .attr("r", nodeRadius)
    .attr("fill", d => {
      if (d.status === "revogado") return "#aaa";
      if (d.status === "suspenso") return "#ddd";
      return d.color || "#888";
    })
    .attr("stroke", d => state.highlightedNodes.has(d.id) ? "#f1c40f" : "rgba(255,255,255,0.3)")
    .attr("stroke-width", d => state.highlightedNodes.has(d.id) ? 3 : 1)
    .attr("opacity", d => d.status === "revogado" ? 0.5 : 1);

  node.filter(d => d.type === "norma" || d.type === "papel" || d.type === "entidade")
    .append("text")
    .attr("dy", d => nodeRadius(d) + 10)
    .attr("text-anchor", "middle")
    .attr("font-size", "9px")
    .attr("font-family", "'JetBrains Mono', monospace")
    .attr("fill", "#3d5166")
    .text(d => d.label?.substring(0, 30) || d.id?.split(":")[1] || "");

  svg.on("click", () => deselectNode());

  simulation.on("tick", () => {
    link
      .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    node.attr("transform", d => `translate(${d.x},${d.y})`);
  });

  function dragStarted(event) {
    if (!event.active) simulation.alphaTarget(0.3).restart();
    event.subject.fx = event.subject.x;
    event.subject.fy = event.subject.y;
  }
  function dragged(event) {
    event.subject.fx = event.x;
    event.subject.fy = event.y;
  }
  function dragEnded(event) {
    if (!event.active) simulation.alphaTarget(0);
    event.subject.fx = null;
    event.subject.fy = null;
  }
}

// ── Node Panel ────────────────────────────────────────────────────────────────
function selectNode(nodeId) {
  state.selectedNodeId = nodeId;
  const node = state.graph.nodes.find(n => n.id === nodeId);
  if (!node) return;

  $("node-panel-title").textContent = node.label || node.id;
  $("node-panel-type").textContent = node.type.toUpperCase() + " · " + (node.status || "");
  $("node-panel-type").className = "status-" + (node.status || "vigente");
  $("node-panel-type").style.color = "";

  const statusBadge = `<span class="status-badge status-${node.status || 'vigente'}">${node.status || 'vigente'}</span>`;

  let summaryHtml = `<div class="panel-section">
    <div class="panel-section-label">Resumo</div>
    <div class="panel-text">${escapeHtml(node.summary || "")} ${statusBadge}</div>
  </div>`;

  if (node.tags && node.tags.length) {
    summaryHtml += `<div class="panel-section">
      <div class="panel-section-label">Tags</div>
      <div class="panel-tags">${node.tags.map(t => `<span class="tag">${t}</span>`).join("")}</div>
    </div>`;
  }

  // Outgoing edges
  const outEdges = state.graph.links.filter(e => (e.source?.id || e.source) === nodeId);
  const inEdges = state.graph.links.filter(e => (e.target?.id || e.target) === nodeId);

  if (outEdges.length) {
    summaryHtml += `<div class="panel-section">
      <div class="panel-section-label">Correlações (saída — ${outEdges.length})</div>
      <ul class="edge-list">${outEdges.slice(0, 10).map(e => edgeHtml(e, "out")).join("")}</ul>
    </div>`;
  }
  if (inEdges.length) {
    summaryHtml += `<div class="panel-section">
      <div class="panel-section-label">Correlações (entrada — ${inEdges.length})</div>
      <ul class="edge-list">${inEdges.slice(0, 10).map(e => edgeHtml(e, "in")).join("")}</ul>
    </div>`;
  }

  $("node-panel-body").innerHTML = summaryHtml;

  // Text section
  const textSection = $("node-text-section");
  if (state.corpusTexts && state.corpusTexts.texts && state.corpusTexts.texts[nodeId]) {
    const ct = state.corpusTexts.texts[nodeId];
    $("node-text-pre").textContent = ct.textoCompleto || "";
    textSection.style.display = "block";
  } else {
    textSection.style.display = "none";
  }

  $("node-panel").classList.add("open");

  // Bind click on edge node links
  $("node-panel-body").querySelectorAll(".edge-node-link").forEach(el => {
    el.addEventListener("click", () => selectNode(el.dataset.nodeid));
  });
}

function edgeHtml(edge, dir) {
  const otherId = dir === "out" ? (edge.target?.id || edge.target) : (edge.source?.id || edge.source);
  const otherNode = state.graph.nodes.find(n => n.id === otherId);
  const otherLabel = otherNode ? (otherNode.label || otherId).substring(0, 40) : otherId;
  const edgeColor = edge.color || "#999";
  const implicitDash = edge.implicit ? " (impl.)" : "";
  return `<li class="edge-item">
    <span class="edge-type-badge" style="background:${edgeColor}20;color:${edgeColor}">${edge.type}</span>
    <span class="edge-node-link" data-nodeid="${escapeHtml(otherId)}">${escapeHtml(otherLabel)}</span>${implicitDash}
  </li>`;
}

function deselectNode() {
  state.selectedNodeId = null;
  $("node-panel").classList.remove("open");
}

// ── Tooltips ──────────────────────────────────────────────────────────────────
function showNodeTooltip(event, d) {
  const tip = $("tooltip");
  tip.innerHTML = `<b>${escapeHtml(d.label || d.id)}</b><br>${d.type} · ${d.status || ""}`;
  tip.style.display = "block";
  tip.style.left = (event.clientX + 12) + "px";
  tip.style.top = (event.clientY + 12) + "px";
}
function showEdgeTooltip(event, d) {
  const tip = $("tooltip");
  tip.innerHTML = `<b>${d.type}</b><br>peso: ${d.weight?.toFixed(2)}${d.implicit ? " · implícita" : ""}`;
  tip.style.display = "block";
  tip.style.left = (event.clientX + 12) + "px";
  tip.style.top = (event.clientY + 12) + "px";
}
function hideTooltip() { $("tooltip").style.display = "none"; }

// ── Hierarchy View ────────────────────────────────────────────────────────────
function populateHierarchyView() {
  const container = $("hierarchy-container");
  if (!state.graph) return;

  const normaNodes = state.graph.nodes.filter(n => n.type === "norma");
  const byLayer = {};
  normaNodes.forEach(n => {
    const layer = n.layer || 9;
    byLayer[layer] = byLayer[layer] || [];
    byLayer[layer].push(n);
  });

  const layerNames = {
    1: "Constituição Federal",
    2: "Lei Complementar / Lei Ordinária",
    3: "Resolução BCB/CMN",
    4: "Circular BCB",
    5: "Instrução Normativa",
    6: "Manual Operacional",
  };

  let html = "";
  Object.keys(byLayer).sort().forEach(level => {
    const name = layerNames[level] || `Nível ${level}`;
    html += `<div class="hierarchy-level">
      <div class="hierarchy-level-title">
        <span class="hierarchy-level-badge">L${level}</span>${name}
      </div>`;
    byLayer[level].forEach(n => {
      const statusClass = "status-" + (n.status || "vigente");
      html += `<div class="norm-card" onclick="selectNode('${escapeHtml(n.id)}'); switchView('graph');">
        <div class="norm-card-name">${escapeHtml(n.label || n.id)}</div>
        <div class="norm-card-meta">
          <span class="status-badge ${statusClass}">${n.status || "vigente"}</span>
          <span style="margin-left:8px">${n.id}</span>
        </div>
      </div>`;
    });
    html += "</div>";
  });
  container.innerHTML = html || "<p>Nenhuma norma encontrada.</p>";
}

// ── Role View ─────────────────────────────────────────────────────────────────
function populateRoleSelect() {
  const select = $("role-select");
  if (!state.graph) return;
  const papeis = state.graph.nodes.filter(n => n.type === "papel" || n.type === "entidade");
  papeis.forEach(n => {
    const opt = document.createElement("option");
    opt.value = n.id;
    opt.textContent = n.label || n.id;
    select.appendChild(opt);
  });
}

function renderRoleObligations(papelId) {
  const container = $("role-obligations");
  if (!papelId) { container.innerHTML = ""; return; }

  const obligationTypes = new Set([
    "obriga", "permite", "proibe", "atribui_responsabilidade", "aplica_a", "condiciona"
  ]);
  const edges = state.graph.links.filter(e => {
    const tgt = e.target?.id || e.target;
    return tgt === papelId && obligationTypes.has(e.type);
  });

  if (!edges.length) {
    container.innerHTML = "<p>Nenhuma obrigação encontrada para este papel.</p>";
    return;
  }

  const papel = state.graph.nodes.find(n => n.id === papelId);
  let html = `<h3 style="font-family:'EB Garamond',serif;font-size:22px;color:#0f2340;margin-bottom:16px">
    Obrigações: ${papel ? (papel.label || papel.id) : papelId}
  </h3>`;

  edges.forEach(e => {
    const srcId = e.source?.id || e.source;
    const srcNode = state.graph.nodes.find(n => n.id === srcId);
    const edgeColor = e.color || "#999";
    html += `<div class="obligation-item">
      <div class="art-ref" style="color:${edgeColor}">${e.type.toUpperCase()}</div>
      <div class="art-text">
        <b>${srcNode ? (srcNode.label || srcId).substring(0, 50) : srcId}</b>
        ${srcNode ? `<br><small>${escapeHtml(srcNode.summary || "")}</small>` : ""}
      </div>
    </div>`;
  });
  container.innerHTML = html;
}

// ── Timeline View ─────────────────────────────────────────────────────────────
function populateTimelineView() {
  const container = $("timeline-container");
  if (!state.diffLog) {
    container.innerHTML = "<p>Nenhum diff-log.json encontrado. Execute o pipeline completo.</p>";
    return;
  }

  const entries = state.diffLog.entries || [];
  if (!entries.length) { container.innerHTML = "<p>Sem alterações registradas.</p>"; return; }

  let html = "";
  entries.slice(0, 100).forEach(e => {
    const date = (e.timestamp || "").substring(0, 10);
    html += `<div class="timeline-item">
      <div class="timeline-date">${date}</div>
      <div class="timeline-content">
        <div class="timeline-title">${escapeHtml(e.corpusFile || "")}</div>
        <div class="timeline-desc">${escapeHtml(e.description || "")}
          <span class="tag" style="margin-left:6px">${e.changeType || ""}</span>
          <span class="tag">${e.impacto || ""}</span>
        </div>
      </div>
    </div>`;
  });
  container.innerHTML = html;
}

// ── Tour View ─────────────────────────────────────────────────────────────────
function populateTourView() {
  const select = $("tour-select");
  // Tours come from graph's tours field if available via GRAPH_DATA
  const tourData = window.TOUR_DATA || [];
  if (!tourData.length) {
    $("tour-steps-panel").innerHTML = "<p style='padding:16px;color:#888'>Nenhum tour disponível.</p>";
    return;
  }

  tourData.forEach((tour, i) => {
    const opt = document.createElement("option");
    opt.value = i; opt.textContent = tour.title;
    select.appendChild(opt);
  });

  renderTour(0);

  select.addEventListener("change", () => {
    state.tourIndex = parseInt(select.value);
    state.tourStepIndex = 0;
    renderTour(state.tourIndex);
  });
}

function renderTour(tourIdx) {
  const tours = window.TOUR_DATA || [];
  if (!tours[tourIdx]) return;
  const tour = tours[tourIdx];
  const steps = tour.steps || [];

  // Steps panel
  const panel = $("tour-steps-panel");
  panel.innerHTML = steps.map((step, i) => `
    <button class="tour-step-btn ${i === state.tourStepIndex ? 'active' : ''}" onclick="goToTourStep(${tourIdx}, ${i})">
      <div class="tour-step-num">Passo ${step.order || i + 1}</div>
      ${escapeHtml(step.title)}
    </button>
  `).join("");

  renderTourStep(tourIdx, state.tourStepIndex);
}

function renderTourStep(tourIdx, stepIdx) {
  state.tourStepIndex = stepIdx;
  const tours = window.TOUR_DATA || [];
  const tour = tours[tourIdx];
  if (!tour) return;
  const steps = tour.steps || [];
  const step = steps[stepIdx];
  if (!step) return;

  // Highlight nodes on graph
  state.highlightedNodes = new Set(step.nodeIds || []);
  if (state.currentView === "graph") renderGraph();

  const nodeIds = step.nodeIds || [];
  const nodeChips = nodeIds.map(id => {
    const n = state.graph?.nodes.find(x => x.id === id);
    return `<span class="tour-node-chip" onclick="selectNode('${escapeHtml(id)}'); switchView('graph');">${escapeHtml(n ? (n.label || id).substring(0, 30) : id)}</span>`;
  }).join("");

  $("tour-content").innerHTML = `
    <h3>${escapeHtml(step.title)}</h3>
    <p>${escapeHtml(step.description || "")}</p>
    ${nodeChips ? `<div class="tour-node-chips">${nodeChips}</div>` : ""}
    <div class="tour-nav">
      <button class="tour-nav-btn" onclick="goToTourStep(${tourIdx}, ${stepIdx - 1})" ${stepIdx === 0 ? "disabled" : ""}>← Anterior</button>
      <button class="tour-nav-btn" onclick="goToTourStep(${tourIdx}, ${stepIdx + 1})" ${stepIdx >= steps.length - 1 ? "disabled" : ""}>Próximo →</button>
    </div>
  `;

  // Update step buttons
  $("tour-steps-panel").querySelectorAll(".tour-step-btn").forEach((btn, i) => {
    btn.classList.toggle("active", i === stepIdx);
  });
}

function goToTourStep(tourIdx, stepIdx) {
  const tours = window.TOUR_DATA || [];
  const tour = tours[tourIdx];
  if (!tour) return;
  const steps = tour.steps || [];
  if (stepIdx < 0 || stepIdx >= steps.length) return;
  renderTourStep(tourIdx, stepIdx);
}

// ── Search ────────────────────────────────────────────────────────────────────
function setupSearch() {
  const input = $("search-input");
  const results = $("search-results");

  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    if (q.length < 2) { results.style.display = "none"; return; }

    const matches = (state.graph?.nodes || [])
      .filter(n =>
        n.label?.toLowerCase().includes(q) ||
        n.summary?.toLowerCase().includes(q) ||
        n.tags?.some(t => t.toLowerCase().includes(q))
      )
      .slice(0, 12);

    if (!matches.length) { results.style.display = "none"; return; }

    results.innerHTML = matches.map(n => `
      <div class="search-result-item" data-nodeid="${escapeHtml(n.id)}">
        <span class="search-result-type">${n.type}</span>${escapeHtml((n.label || n.id).substring(0, 50))}
      </div>
    `).join("");

    results.style.display = "block";
    results.querySelectorAll(".search-result-item").forEach(el => {
      el.addEventListener("click", () => {
        selectNode(el.dataset.nodeid);
        switchView("graph");
        results.style.display = "none";
        input.value = "";
      });
    });
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#search-box")) results.style.display = "none";
  });
}

// ── View Switching ────────────────────────────────────────────────────────────
function switchView(viewName) {
  state.currentView = viewName;
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.querySelectorAll(".sidebar-btn[data-view]").forEach(b => b.classList.remove("active"));

  const viewEl = $(`${viewName}-view`);
  if (viewEl) viewEl.classList.add("active");

  const btnEl = $q(`.sidebar-btn[data-view="${viewName}"]`);
  if (btnEl) btnEl.classList.add("active");

  if (viewName === "graph" && state.graph) {
    // Re-render graph if needed (window resize)
    setTimeout(() => { if (!state.simulation) renderGraph(); }, 50);
  }
}

// ── Events ────────────────────────────────────────────────────────────────────
function bindEvents() {
  // View buttons
  document.querySelectorAll(".sidebar-btn[data-view]").forEach(btn => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  // Filters
  $("filter-node-type").addEventListener("change", (e) => {
    state.filters.nodeType = e.target.value;
    renderGraph();
  });
  $("filter-status").addEventListener("change", (e) => {
    state.filters.status = e.target.value;
    renderGraph();
  });
  $("filter-edge-type").addEventListener("change", (e) => {
    state.filters.edgeType = e.target.value;
    renderGraph();
  });
  $("filter-implicit").addEventListener("change", (e) => {
    state.filters.implicit = e.target.value;
    renderGraph();
  });
  $("filter-weight").addEventListener("input", (e) => {
    state.filters.minWeight = parseFloat(e.target.value);
    $("filter-weight-val").textContent = state.filters.minWeight.toFixed(1);
    renderGraph();
  });

  // Role select
  $("role-select").addEventListener("change", (e) => renderRoleObligations(e.target.value));

  // Node panel close
  $("panel-close-btn").addEventListener("click", deselectNode);

  // Search
  setupSearch();

  // Window resize
  window.addEventListener("resize", () => {
    if (state.currentView === "graph") renderGraph();
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", init);
