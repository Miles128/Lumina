/**
 * Pure workflow ↔ canvas graph helpers (no DOM).
 * Used by workflows.js and unit-tested in Node.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.LuminaWorkflowGraph = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const KIND_IO = {
    skill: { inputs: 1, outputs: 1 },
    agent: { inputs: 1, outputs: 1 },
    branch: { inputs: 1, outputs: 2 },
  };

  function kindIo(kind) {
    return KIND_IO[kind] || KIND_IO.agent;
  }

  function nodeHtml(kind, label) {
    const k = String(kind || "agent");
    const title = String(label || k);
    return (
      `<div class="wf-node-card wf-kind-${escapeAttr(k)}">` +
      `<span class="wf-node-kind">${escapeHtml(k)}</span>` +
      `<span class="wf-node-label">${escapeHtml(title)}</span>` +
      `</div>`
    );
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/'/g, "&#39;");
  }

  function defaultLabel(node) {
    const kind = node.kind || "agent";
    if (kind === "skill") {
      return node.config?.skill_name || node.id;
    }
    if (kind === "agent") {
      const prompt = String(node.config?.prompt_template || "");
      return prompt ? prompt.slice(0, 28) : node.id;
    }
    if (kind === "branch") {
      return node.config?.condition?.path || node.id;
    }
    return node.id;
  }

  /** Build Drawflow import payload from WorkflowDef. */
  function workflowToDrawflow(workflow) {
    const nodes = Array.isArray(workflow?.nodes) ? workflow.nodes : [];
    const edges = Array.isArray(workflow?.edges) ? workflow.edges : [];
    const data = {};
    const idMap = {}; // workflowId -> drawflow numeric id

    nodes.forEach((node, index) => {
      const dfId = index + 1;
      idMap[node.id] = dfId;
      const io = kindIo(node.kind);
      const pos = node.config?._canvas || {};
      const x = Number.isFinite(pos.x) ? pos.x : 80 + index * 240;
      const y = Number.isFinite(pos.y) ? pos.y : 120 + (index % 2) * 40;
      const outputs = {};
      for (let i = 1; i <= io.outputs; i += 1) {
        outputs[`output_${i}`] = { connections: [] };
      }
      const inputs = {};
      for (let i = 1; i <= io.inputs; i += 1) {
        inputs[`input_${i}`] = { connections: [] };
      }
      data[String(dfId)] = {
        id: dfId,
        name: node.kind || "agent",
        data: {
          workflowId: node.id,
          kind: node.kind || "agent",
          config: { ...(node.config || {}) },
          on_failure: node.on_failure || "stop",
          inputs_schema: node.inputs_schema || {},
          outputs_schema: node.outputs_schema || {},
        },
        class: `wf-${node.kind || "agent"}`,
        html: nodeHtml(node.kind, defaultLabel(node)),
        typenode: false,
        inputs,
        outputs,
        pos_x: x,
        pos_y: y,
      };
    });

    for (const edge of edges) {
      const fromId = idMap[edge.from || edge.from_id];
      const toId = idMap[edge.to || edge.to_id];
      if (!fromId || !toId) continue;
      const fromNode = data[String(fromId)];
      const toNode = data[String(toId)];
      if (!fromNode || !toNode) continue;
      const port = edge.port || "default";
      let outputKey = "output_1";
      if (fromNode.data.kind === "branch") {
        const truePort = fromNode.data.config?.true_port || "yes";
        outputKey = port === truePort ? "output_1" : "output_2";
      }
      fromNode.outputs[outputKey] = fromNode.outputs[outputKey] || { connections: [] };
      toNode.inputs.input_1 = toNode.inputs.input_1 || { connections: [] };
      fromNode.outputs[outputKey].connections.push({
        node: String(toId),
        output: "input_1",
      });
      toNode.inputs.input_1.connections.push({
        node: String(fromId),
        input: outputKey,
      });
    }

    return {
      drawflow: {
        Home: {
          data,
        },
      },
    };
  }

  /** Export Drawflow editor state back to WorkflowDef fields. */
  function drawflowToWorkflow(exported, meta) {
    const home = exported?.drawflow?.Home?.data || {};
    const nodes = [];
    const edges = [];
    const entries = Object.values(home);

    for (const item of entries) {
      const data = item.data || {};
      const workflowId = String(data.workflowId || `n${item.id}`);
      const config = { ...(data.config || {}) };
      config._canvas = { x: item.pos_x, y: item.pos_y };
      nodes.push({
        id: workflowId,
        kind: data.kind || item.name || "agent",
        config,
        inputs_schema: data.inputs_schema || {},
        outputs_schema: data.outputs_schema || {},
        on_failure: data.on_failure || "stop",
      });
    }

    const idByDf = {};
    for (const item of entries) {
      idByDf[String(item.id)] = String((item.data || {}).workflowId || `n${item.id}`);
    }

    for (const item of entries) {
      const fromId = idByDf[String(item.id)];
      const outputs = item.outputs || {};
      for (const [outputKey, bucket] of Object.entries(outputs)) {
        const connections = bucket?.connections || [];
        for (const conn of connections) {
          const toId = idByDf[String(conn.node)];
          if (!fromId || !toId) continue;
          let port = "default";
          if ((item.data || {}).kind === "branch") {
            const truePort = item.data.config?.true_port || "yes";
            const falsePort = item.data.config?.false_port || "no";
            port = outputKey === "output_1" ? truePort : falsePort;
          }
          edges.push({ from: fromId, to: toId, port });
        }
      }
    }

    return {
      name: meta?.name || "untitled",
      version: meta?.version || 1,
      inputs_schema: meta?.inputs_schema || {},
      outputs_schema: meta?.outputs_schema || {},
      nodes,
      edges,
    };
  }

  function newNodeSpec(kind, index) {
    const id = `${kind}_${Date.now().toString(36)}_${index}`;
    if (kind === "skill") {
      return {
        id,
        kind: "skill",
        config: { skill_name: "echo", _canvas: { x: 120, y: 140 } },
        inputs_schema: {},
        outputs_schema: { output: "string" },
        on_failure: "stop",
      };
    }
    if (kind === "branch") {
      return {
        id,
        kind: "branch",
        config: {
          condition: { type: "expr", path: "flag", op: "eq", value: "yes" },
          ports: ["yes", "no"],
          true_port: "yes",
          false_port: "no",
          _canvas: { x: 120, y: 140 },
        },
        inputs_schema: {},
        outputs_schema: {},
        on_failure: "stop",
      };
    }
    return {
      id,
      kind: "agent",
      config: {
        prompt_template: "处理上游结果并输出 summary",
        _canvas: { x: 120, y: 140 },
      },
      inputs_schema: {},
      outputs_schema: { summary: "string" },
      on_failure: "stop",
    };
  }

  return {
    kindIo,
    nodeHtml,
    defaultLabel,
    workflowToDrawflow,
    drawflowToWorkflow,
    newNodeSpec,
  };
});
