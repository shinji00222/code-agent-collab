from __future__ import annotations


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Workbench</title>
<style>
  :root {
    --bg: #030303;
    --bg-2: #080808;
    --text: #e9e5ee;
    --muted: #8c858f;
    --dim: #303034;
    --line: #1a191d;
    --purple: #b86cff;
    --purple-2: #d19cff;
    --green: #74e083;
    --red: #ff7b72;
    --amber: #e9c46a;
    --mono: Consolas, "Cascadia Mono", "Courier New", "Microsoft YaHei UI", monospace;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    overflow: hidden;
    background:
      linear-gradient(rgba(255,255,255,0.018) 1px, transparent 1px),
      radial-gradient(circle at 38% 28%, rgba(184,108,255,0.12), transparent 32%),
      var(--bg);
    background-size: 100% 3px, 100% 100%, 100% 100%;
    color: var(--text);
    font-family: var(--mono);
    letter-spacing: 0;
  }
  button, input { font: inherit; }
  button {
    border: 1px solid #242228;
    background: #0b0b0e;
    color: var(--muted);
    cursor: pointer;
  }
  button:hover, button:focus-visible {
    color: var(--text);
    border-color: #54415f;
    outline: none;
  }
  .terminal {
    height: 100vh;
    display: grid;
    grid-template-rows: 58px minmax(0, 1fr) 76px;
    background: rgba(0,0,0,0.7);
  }
  .statusline {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr 1fr;
    align-items: center;
    gap: 16px;
    border-bottom: 1px solid rgba(184,108,255,0.52);
    padding: 0 24px;
    color: var(--muted);
    white-space: nowrap;
  }
  .statusline strong {
    color: var(--purple-2);
    font-weight: 700;
  }
  .statusline .ok { color: var(--green); }
  .screen {
    min-height: 0;
    overflow: auto;
    padding: 22px 24px 36px;
  }
  .transcript {
    max-width: 1160px;
  }
  .line {
    min-height: 26px;
    color: #d8d3dc;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .time {
    color: #4d4a52;
  }
  .prompt {
    color: var(--purple-2);
  }
  .muted {
    color: var(--muted);
  }
  .tree-shell {
    margin: 24px 0 20px 118px;
    width: min(520px, calc(100vw - 150px));
  }
  .tree-title {
    color: var(--muted);
    margin-bottom: 14px;
  }
  .tree-canvas {
    position: relative;
    min-height: 470px;
    padding: 4px 0 12px;
  }
  .tree-node {
    position: relative;
    display: grid;
    grid-template-columns: 26px minmax(0, 1fr);
    align-items: start;
    gap: 10px;
    color: #3a3840;
    width: 360px;
    min-height: 53px;
    margin-left: 20px;
  }
  .tree-node::after {
    content: "";
    position: absolute;
    left: 10px;
    top: 25px;
    bottom: -2px;
    width: 2px;
    background-image: linear-gradient(var(--dim) 48%, transparent 0);
    background-size: 2px 8px;
  }
  .tree-node.done::after, .tree-node.running::after {
    background: var(--purple);
    box-shadow: 0 0 16px rgba(184,108,255,0.45);
  }
  .tree-node:last-child::after, .tree-node.no-tail::after { display: none; }
  .dot {
    position: relative;
    z-index: 2;
    width: 24px;
    height: 24px;
    border: 3px solid var(--dim);
    border-radius: 50%;
    background: #050505;
    box-shadow: 0 0 0 5px #050505;
  }
  .dot::after {
    content: "";
    position: absolute;
    inset: 6px;
    border-radius: 50%;
    background: transparent;
  }
  .label {
    padding-top: 1px;
    color: #55525a;
    font-size: 16px;
    line-height: 1.2;
    white-space: nowrap;
  }
  .node-body {
    width: max-content;
    max-width: 220px;
    padding: 0 7px 4px 0;
    background: rgba(3,3,3,0.88);
  }
  .detail {
    margin-top: 5px;
    color: #39363e;
    font-size: 12px;
    line-height: 1.35;
  }
  .done .dot, .done.branch-child .dot {
    border-color: var(--purple);
    background: var(--purple);
  }
  .done .dot::after {
    content: "✓";
    inset: -1px 0 0 0;
    display: grid;
    place-items: center;
    color: #09040f;
    font-size: 16px;
    font-weight: 900;
    background: transparent;
  }
  .done .label, .done.branch-child .label {
    color: var(--purple-2);
  }
  .done .detail, .done.branch-child .detail {
    color: #8f62b5;
  }
  .running .dot, .running.branch-child .dot {
    border-color: var(--purple-2);
    background: #09040f;
    box-shadow:
      0 0 0 5px #050505,
      0 0 0 10px rgba(184,108,255,0.18),
      0 0 28px rgba(184,108,255,0.95);
  }
  .running .dot::before {
    content: "";
    position: absolute;
    inset: -10px;
    border: 1px dotted rgba(184,108,255,0.68);
    border-radius: 50%;
    animation: spin 1.4s linear infinite;
  }
  .running .dot::after {
    background: var(--purple);
    box-shadow: 0 0 16px rgba(209,156,255,0.92);
  }
  .running .label, .running.branch-child .label {
    color: #f4e9ff;
    text-shadow: 0 0 18px rgba(184,108,255,0.7);
  }
  .running .detail, .running.branch-child .detail {
    color: var(--purple-2);
  }
  .waiting .dot, .waiting.branch-child .dot {
    border-color: var(--amber);
    background: rgba(233,196,106,0.18);
  }
  .waiting .label, .waiting.branch-child .label {
    color: var(--amber);
  }
  .failed .dot, .failed.branch-child .dot {
    border-color: var(--red);
    background: rgba(255,123,114,0.2);
  }
  .failed .label, .failed.branch-child .label {
    color: var(--red);
  }
  .branch {
    position: relative;
    width: 360px;
    max-width: 100%;
    margin: -5px 0 0 46px;
  }
  .branch.continues::before {
    content: "";
    position: absolute;
    left: -16px;
    top: -2px;
    bottom: -2px;
    width: 2px;
    background-image: linear-gradient(var(--dim) 48%, transparent 0);
    background-size: 2px 8px;
  }
  .branch.reached.continues::before {
    background: var(--purple);
    box-shadow: 0 0 16px rgba(184,108,255,0.45);
  }
  .branch-child {
    margin-left: 0;
    padding-left: 42px;
    width: 390px;
    min-width: 0;
  }
  .branch-child::before {
    content: "";
    position: absolute;
    left: 10px;
    top: -28px;
    bottom: -2px;
    width: 2px;
    background-image: linear-gradient(var(--dim) 48%, transparent 0);
    background-size: 2px 8px;
  }
  .branch-child:last-child::before {
    bottom: 41px;
  }
  .branch-child::after {
    left: 52px;
  }
  .branch-child::before, .branch-child .branch-arm {
    pointer-events: none;
  }
  .branch-child::after {
    background-image: linear-gradient(var(--dim) 48%, transparent 0);
    background-size: 2px 8px;
  }
  .branch-child .dot::before {
    content: "";
    position: absolute;
    left: -44px;
    top: 8px;
    width: 43px;
    height: 2px;
    background-image: linear-gradient(90deg, var(--dim) 50%, transparent 0);
    background-size: 8px 2px;
  }
  .branch-child .label {
    white-space: normal;
  }
  .join {
    display: none;
  }
  .tree-empty {
    color: var(--muted);
    margin-left: 20px;
  }
  .quickbar {
    display: flex;
    gap: 8px;
    margin-top: 22px;
    flex-wrap: wrap;
  }
  .quickbar button {
    min-height: 30px;
    border-radius: 4px;
    padding: 4px 9px;
    font-size: 12px;
  }
  .quickbar .collab-switch {
    border-color: rgba(184,108,255,0.78);
    color: var(--purple-2);
    box-shadow: 0 0 14px rgba(184,108,255,0.16);
  }
  .quickbar .pause-switch {
    border-color: rgba(233,196,106,0.85);
    color: #f3d88a;
    box-shadow: 0 0 16px rgba(233,196,106,0.16);
  }
  .quickbar .force-switch {
    border-color: rgba(255,123,114,0.95);
    color: #ffb3ad;
    box-shadow: 0 0 18px rgba(255,123,114,0.18);
  }
  .mode-hint {
    margin-top: 10px;
    color: #6f6875;
    font-size: 12px;
  }
  .output {
    margin-top: 10px;
    max-width: 1040px;
    color: #bcb6c3;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .output .err { color: var(--red); }
  .output .cmdline { color: var(--purple-2); }
  .composer {
    border-top: 1px solid #242228;
    display: grid;
    grid-template-columns: 28px minmax(0, 1fr) 44px;
    align-items: center;
    gap: 10px;
    padding: 16px 24px 20px;
    background: linear-gradient(180deg, rgba(3,3,3,0.2), #030303 40%);
  }
  .composer .prompt {
    font-size: 22px;
  }
  #goal {
    width: 100%;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--text);
    font-size: 18px;
    min-height: 34px;
  }
  #goal::placeholder { color: #4e4b53; }
  .send {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    color: #0a080d;
    background: var(--purple-2);
    border-color: var(--purple-2);
    font-size: 20px;
    line-height: 1;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  @media (prefers-reduced-motion: reduce) {
    .running .dot::before { animation: none; }
  }
  @media (max-width: 760px) {
    .terminal { grid-template-rows: auto minmax(0, 1fr) 70px; }
    .statusline {
      grid-template-columns: 1fr 1fr;
      row-gap: 6px;
      padding: 12px 14px;
      font-size: 12px;
    }
    .screen { padding: 14px 14px 28px; }
    .tree-shell {
      margin-left: 0;
      width: 100%;
      height: 350px;
      overflow: visible;
    }
    .tree-canvas {
      width: 520px;
      min-width: 520px;
      min-height: 600px;
      transform: scale(0.66);
      transform-origin: left top;
    }
    .branch {
      max-width: none;
    }
    .composer {
      grid-template-columns: 22px minmax(0, 1fr) 38px;
      padding: 12px 14px 16px;
    }
    #goal { font-size: 15px; }
    .send { width: 36px; height: 36px; }
  }
</style>
</head>
<body>
<main class="terminal">
  <header class="statusline">
    <div><strong>Agent Workbench</strong></div>
    <div>provider: <span class="ok" id="providerText">mock</span></div>
    <div>model: <span class="ok" id="modelText">mock-model</span></div>
    <div>status: <span class="ok" id="runStatus">idle</span></div>
  </header>
  <section class="screen" id="screen">
    <div class="transcript">
      <div class="line"><span class="time">[17:20:14]</span> <span class="prompt">&gt;</span> run-adaptive build terminal tree progress</div>
      <div class="line"><span class="time">[17:20:15]</span> coderagent complete -> ReviewerAgent reviewing -> Fix Loop if needed</div>
      <div class="line"><span class="time">[17:20:15]</span> <span class="muted" id="progressDetail">waiting for local workflow state</span></div>
      <section class="tree-shell" aria-label="Agent 关系与进度">
        <div class="tree-title" id="progressSummaryInline">latest task: loading</div>
        <div class="tree-canvas" id="agentTreeInline">
          <div class="tree-empty">正在读取本地方案和工作流日志。</div>
        </div>
      </section>
      <div class="quickbar">
        <button class="collab-switch" id="createPlan" type="button">生成主控方案</button>
        <button class="collab-switch" id="startCollab" type="button">开始协同工作</button>
        <button class="pause-switch" id="pauseWork" type="button">暂停工作</button>
        <button class="force-switch" id="forceStop" type="button">强制停止</button>
        <button data-fill='run-adaptive "实现终端树状进度"'>run-adaptive</button>
        <button data-fill='plans'>plans</button>
        <button data-fill='approve '>approve</button>
        <button data-fill='run "实现终端树状进度"'>run</button>
        <button data-fill='provider'>provider</button>
        <button data-fill='help'>help</button>
      </div>
      <div class="mode-hint" id="modeHint">默认：先和第一个 AI 对话澄清需求；点“生成主控方案”后只生成方案；点“开始协同工作”才执行后续 Agent；“暂停工作”为软暂停，“强制停止”会立即中断后台进程。</div>
      <pre class="output" id="output">&gt; provider
当前 Provider：mock
模型：mock-model
接口地址：本地模拟，不联网
密钥环境变量：未配置
密钥状态：未配置</pre>
    </div>
  </section>
  <section class="composer">
    <span class="prompt">&gt;</span>
    <input id="goal" autocomplete="off" spellcheck="false" placeholder="输入命令，或直接写任务目标">
    <button class="send" id="runTask" title="运行">↑</button>
  </section>
</main>
<script>
  const output = document.getElementById("output");
  const goalInput = document.getElementById("goal");
  const runStatus = document.getElementById("runStatus");
  const providerText = document.getElementById("providerText");
  const modelText = document.getElementById("modelText");
  const progressDetail = document.getElementById("progressDetail");
  const progressSummaryInline = document.getElementById("progressSummaryInline");
  const agentTreeInline = document.getElementById("agentTreeInline");
  const screen = document.getElementById("screen");
  const createPlan = document.getElementById("createPlan");
  const startCollab = document.getElementById("startCollab");
  const pauseWork = document.getElementById("pauseWork");
  const forceStop = document.getElementById("forceStop");
  const modeHint = document.getElementById("modeHint");
  let latestProgress = null;
  let progressTimer = null;

  function setText(node, text) {
    if (node) node.textContent = text;
  }

  function nowStamp() {
    return new Date().toTimeString().slice(0, 8);
  }

  function append(text, className = "out") {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = text;
    output.appendChild(document.createTextNode("\\n"));
    output.appendChild(span);
    screen.scrollTop = screen.scrollHeight;
  }

  function quoteArg(text) {
    return `"${String(text).replace(/\\\\/g, "\\\\\\\\").replace(/"/g, "\\\\\\"")}"`;
  }

  function statusText(status) {
    const labels = {
      done: "done",
      waiting: "waiting",
      running: "running",
      paused: "paused",
      idle: "",
      failed: "failed",
    };
    return Object.prototype.hasOwnProperty.call(labels, status) ? labels[status] : status || "";
  }

  function renderNode(node, className = "tree-node", noTail = false) {
    const wrap = document.createElement("div");
    wrap.className = `${className} ${node.status || "idle"}${noTail ? " no-tail" : ""}`;
    const dot = document.createElement("span");
    dot.className = "dot";
    const body = document.createElement("div");
    body.className = "node-body";
    const label = document.createElement("div");
    label.className = "label";
    label.textContent = node.label || "";
    const detail = document.createElement("div");
    detail.className = "detail";
    const state = statusText(node.status);
    const extra = node.detail || "";
    detail.textContent = state && extra ? `${state} · ${extra}` : state || extra;
    body.appendChild(label);
    body.appendChild(detail);
    wrap.appendChild(dot);
    wrap.appendChild(body);
    return wrap;
  }

  function branchReached(children) {
    return children.some((child) => ["done", "running", "failed"].includes(child.status));
  }

  function renderBranch(children, continues = true) {
    const branch = document.createElement("div");
    branch.className = `branch ${branchReached(children || []) ? "reached" : ""}${continues ? " continues" : ""}`;
    (children || []).forEach((child) => {
      branch.appendChild(renderNode(child, "tree-node branch-child", true));
    });
    return branch;
  }

  function renderProgress(data) {
    latestProgress = data;
    const runtime = data.runtime || {};
    const plan = data.latest_plan || {};
    const nodes = data.nodes || [];
    const task = runtime.goal || plan.goal || "暂无任务";
    const state = runtime.status || plan.status || "idle";
    setText(progressSummaryInline, `latest task: ${task}  |  state: ${state}`);
    setText(progressDetail, runtime.detail || "local workflow snapshot loaded");
    setText(runStatus, state === "已执行" ? "done" : state);

    agentTreeInline.innerHTML = "";
    if (!nodes.length) {
      const empty = document.createElement("div");
      empty.className = "tree-empty";
      empty.textContent = "暂无可展示的 Agent 进度。先运行 run 或 run-adaptive。";
      agentTreeInline.appendChild(empty);
      return;
    }

    nodes.forEach((node, index) => {
      if (node.kind === "branch") {
        agentTreeInline.appendChild(renderBranch(node.children || [], index < nodes.length - 1));
        return;
      }
      agentTreeInline.appendChild(renderNode(node, "tree-node", index === nodes.length - 1));
    });
  }

  async function refreshProgress() {
    try {
      const resp = await fetch("/api/progress", { cache: "no-store" });
      const data = await resp.json();
      if (resp.ok) renderProgress(data);
    } catch (e) {
      agentTreeInline.innerHTML = '<div class="tree-empty">进度读取失败。</div>';
    }
  }

  function startPolling() {
    if (progressTimer) return;
    progressTimer = setInterval(refreshProgress, 500);
  }

  function stopPollingSoon() {
    setTimeout(() => {
      if (progressTimer) {
        clearInterval(progressTimer);
        progressTimer = null;
      }
      refreshProgress();
    }, 700);
  }

  async function run(command) {
    if (!command.trim()) return;
    setText(runStatus, "running");
    append(`[${nowStamp()}] > ${command}`, "cmdline");
    startPolling();
    try {
      const resp = await fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        append(data.error || "请求失败", "err");
        setText(runStatus, "failed");
        stopPollingSoon();
        return;
      }
      append(data.output || "命令已完成。", data.code === 0 || data.code === 3 ? "out" : "err");
      setText(runStatus, data.code === 0 ? "done" : data.code === 3 ? "paused" : "failed");
      if (command === "provider" && data.output) {
        const providerMatch = data.output.match(/当前 Provider：(.+)/);
        const modelMatch = data.output.match(/模型：(.+)/);
        if (providerMatch) setText(providerText, providerMatch[1].trim());
        if (modelMatch) setText(modelText, modelMatch[1].trim());
      }
    } catch (e) {
      append(`网络错误：${String(e)}`, "err");
      setText(runStatus, "failed");
    } finally {
      stopPollingSoon();
    }
  }

  async function discuss(message) {
    if (!message.trim()) return;
    setText(runStatus, "discussing");
    append(`[${nowStamp()}] shin: ${message}`, "cmdline");
    try {
      const resp = await fetch("/api/discuss", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        append(data.error || "讨论请求失败", "err");
        setText(runStatus, "failed");
        return;
      }
      append(`[${nowStamp()}] OrchestratorAgent: ${data.output || "我已记录。"}`, "out");
      setText(runStatus, "discuss");
    } catch (e) {
      append(`网络错误：${String(e)}`, "err");
      setText(runStatus, "failed");
    }
  }

  function fill(command) {
    goalInput.value = command;
    goalInput.focus();
  }

  async function beginCollaboration() {
    await refreshProgress();
    const plan = latestProgress && latestProgress.latest_plan ? latestProgress.latest_plan : {};
    const taskId = plan.task_id || "";
    if (!taskId) {
      append("还没有可执行的主控方案。先输入任务目标，让 OrchestratorAgent 生成计划。", "err");
      goalInput.focus();
      return;
    }
    if (plan.status === "已执行" || (latestProgress.runtime || {}).status === "done") {
      append(`最近方案已经执行过：${taskId}`, "out");
      return;
    }
    if (startCollab) startCollab.disabled = true;
    setText(modeHint, `协同工作已开启：正在批准并执行 ${taskId}`);
    await run(`approve ${taskId}`);
    if (startCollab) startCollab.disabled = false;
    setText(modeHint, "默认：先和第一个 AI 对话澄清需求；点“生成主控方案”后只生成方案；点“开始协同工作”才执行后续 Agent；“暂停工作”为软暂停，“强制停止”会立即中断后台进程。");
  }

  async function createPlanFromDiscussion() {
    const typed = goalInput.value.trim();
    if (typed && !/^(pending|plans|review|provider|help|confirm|discard|demo|start|run|run-adaptive|approve)\\b/.test(typed)) {
      await discuss(typed);
      goalInput.value = "";
    }
    try {
      const resp = await fetch("/api/discussion", { cache: "no-store" });
      const data = await resp.json();
      const goal = (data.goal || "").trim();
      if (!goal) {
        append("还没有讨论内容。先直接输入你的想法，我会先问问题。", "err");
        goalInput.focus();
        return;
      }
      setText(modeHint, "正在把讨论内容整理成主控方案；还不会执行后续 Agent。");
      await run(`run-adaptive ${quoteArg(goal)}`);
      setText(modeHint, "方案已生成。继续讨论可补充需求；要执行后续 Agent 再点“开始协同工作”。");
    } catch (e) {
      append(`生成方案失败：${String(e)}`, "err");
      setText(runStatus, "failed");
    }
  }

  async function pauseCurrentWork() {
    if (pauseWork) pauseWork.disabled = true;
    try {
      const resp = await fetch("/api/pause", { method: "POST" });
      const data = await resp.json();
      append(`[${nowStamp()}] ! pause`, "cmdline");
      append(data.output || "已发送暂停请求。", resp.ok ? "out" : "err");
      setText(runStatus, resp.ok ? "pausing" : "failed");
      startPolling();
      stopPollingSoon();
    } catch (e) {
      append(`暂停失败：${String(e)}`, "err");
      setText(runStatus, "failed");
    } finally {
      if (pauseWork) pauseWork.disabled = false;
    }
  }

  async function forceStopCurrentWork() {
    const first = window.confirm("强制停止会立刻中断正在运行的后台 Agent/AI 进程，可能来不及保存完整断点。确定继续？");
    if (!first) return;
    const second = window.confirm("再次确认：这不是软暂停，会直接停止当前后台进程。");
    if (!second) return;
    const phrase = window.prompt("请输入 STOP 确认强制停止：");
    if (phrase !== "STOP") {
      append("强制停止已取消：确认词不匹配。", "err");
      return;
    }
    if (forceStop) forceStop.disabled = true;
    try {
      const resp = await fetch("/api/force-stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: phrase }),
      });
      const data = await resp.json();
      append(`[${nowStamp()}] ! force-stop`, "cmdline");
      append(data.output || "已发送强制停止请求。", resp.ok ? "out" : "err");
      setText(runStatus, resp.ok ? "stopped" : "failed");
      stopPollingSoon();
    } catch (e) {
      append(`强制停止失败：${String(e)}`, "err");
      setText(runStatus, "failed");
    } finally {
      if (forceStop) forceStop.disabled = false;
    }
  }

  document.querySelectorAll("[data-fill]").forEach((button) => {
    button.addEventListener("click", () => fill(button.dataset.fill));
  });

  startCollab.addEventListener("click", () => {
    beginCollaboration();
  });

  createPlan.addEventListener("click", () => {
    createPlanFromDiscussion();
  });

  pauseWork.addEventListener("click", () => {
    pauseCurrentWork();
  });

  forceStop.addEventListener("click", () => {
    forceStopCurrentWork();
  });

  document.getElementById("runTask").addEventListener("click", () => {
    const goal = goalInput.value.trim();
    if (!goal) return;
    if (/^(pending|plans|review|provider|help|confirm|discard|demo|start|run|run-adaptive|approve)\\b/.test(goal)) {
      run(goal);
    } else {
      discuss(goal);
    }
    goalInput.value = "";
  });

  goalInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") document.getElementById("runTask").click();
  });

  refreshProgress();
  setInterval(refreshProgress, 2500);
</script>
</body>
</html>
"""
