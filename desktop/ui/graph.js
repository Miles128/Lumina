(function () {
  "use strict";

  const canvas = document.getElementById("graph-canvas");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  let nodes = [];
  let edges = [];
  let simNodes = [];
  let animationId = null;

  const colors = {
    topic: "#0a0a0a",
    file: "#333333",
    tag: "#666666",
    person: "#0a0a0a",
    trait: "#555555",
    source: "#777777",
    memory: "#999999",
  };

  function resize() {
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
  }

  function loadGraph(filter) {
    window.SecretaryAPI.request("GET", `/api/graph?filter=${filter}`).then((data) => {
      nodes = data.nodes || [];
      edges = data.edges || [];
      initSimulation();
    });
  }

  function initSimulation() {
    simNodes = nodes.map((node, index) => ({
      ...node,
      x: canvas.width / 2 + (Math.random() - 0.5) * 120,
      y: canvas.height / 2 + (Math.random() - 0.5) * 120,
      vx: 0,
      vy: 0,
      radius: node.type === "person" ? 18 : node.type === "topic" ? 14 : 10,
    }));

    const nodeMap = Object.fromEntries(simNodes.map((node) => [node.id, node]));
    edges = edges
      .map((edge) => ({ source: nodeMap[edge.source], target: nodeMap[edge.target], relation: edge.relation }))
      .filter((edge) => edge.source && edge.target);

    if (animationId) cancelAnimationFrame(animationId);
    tick();
  }

  function tick() {
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;

    for (const node of simNodes) {
      node.vx += (centerX - node.x) * 0.0004;
      node.vy += (centerY - node.y) * 0.0004;
    }

    for (let i = 0; i < simNodes.length; i += 1) {
      for (let j = i + 1; j < simNodes.length; j += 1) {
        const a = simNodes[i];
        const b = simNodes[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.max(40, Math.hypot(dx, dy));
        const force = 900 / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx -= fx;
        a.vy -= fy;
        b.vx += fx;
        b.vy += fy;
      }
    }

    for (const edge of edges) {
      const dx = edge.target.x - edge.source.x;
      const dy = edge.target.y - edge.source.y;
      const dist = Math.max(20, Math.hypot(dx, dy));
      const force = (dist - 110) * 0.004;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      edge.source.vx += fx;
      edge.source.vy += fy;
      edge.target.vx -= fx;
      edge.target.vy -= fy;
    }

    for (const node of simNodes) {
      node.vx *= 0.86;
      node.vy *= 0.86;
      node.x += node.vx;
      node.y += node.vy;
      node.x = Math.max(30, Math.min(canvas.width - 30, node.x));
      node.y = Math.max(30, Math.min(canvas.height - 30, node.y));
    }

    draw();
    animationId = requestAnimationFrame(tick);
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.lineWidth = 1;
    for (const edge of edges) {
      ctx.strokeStyle = "rgba(0, 0, 0, 0.08)";
      ctx.beginPath();
      ctx.moveTo(edge.source.x, edge.source.y);
      ctx.lineTo(edge.target.x, edge.target.y);
      ctx.stroke();
    }

    for (const node of simNodes) {
      ctx.beginPath();
      ctx.fillStyle = colors[node.type] || "#999999";
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#666666";
      ctx.font = "11px PingFang SC, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(node.name.slice(0, 8), node.x, node.y + node.radius + 12);
    }
  }

  window.GraphModule = {
    init() {
      resize();
      window.addEventListener("resize", resize);
      document.querySelectorAll("[data-graph-filter]").forEach((button) => {
        button.addEventListener("click", () => {
          document.querySelectorAll("[data-graph-filter]").forEach((item) => item.classList.remove("active"));
          button.classList.add("active");
          loadGraph(button.dataset.graphFilter);
        });
      });
      loadGraph("personal");
    },
    reload(filter) {
      loadGraph(filter || "personal");
    },
  };
})();
