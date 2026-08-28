from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 打包（PyInstaller）模式下没有 __file__，项目根目录取 exe 所在目录；
# 开发模式下是仓库根目录（src/code_agent_collab/webui.py 向上三级）。
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
    SRC_DIR = PROJECT_ROOT
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    SRC_DIR = PROJECT_ROOT / "src"

# 打包模式下 run_cli 调用的同目录 CLI 可执行程序名
CLI_EXE_NAME = "AgentWorkbench-CLI.exe"

ALLOWED_COMMANDS = {
    "init",
    "start",
    "reflect",
    "pending",
    "review",
    "confirm",
    "discard",
    "demo",
    "run",
    "run-adaptive",
    "approve",
    "plans",
    "provider",
    "help",
}

HELP_TEXT = """可用命令（在下面输入框输入后回车）：

  help                    显示本帮助
  provider                查看当前 AI Provider 配置
  init                    生成/重置本地配置
  start "任务目标"         生成任务上下文包
  run "任务目标"           跑完整多 Agent 工作流
  run-adaptive "任务目标"   生成半动态自适应方案（等待人工审批）
  plans                   列出已保存的主控方案
  approve "任务ID或关键词"  批准方案并执行 workers
  demo "任务目标"          一键演示闭环
  pending                 列出待确认候选记录
  review                  审查候选记录（通过后需 confirm 才入库）
  confirm "候选关键词"     人工确认候选入库
  discard "候选关键词"     废弃候选记录

示例：
  run-adaptive "写一个待办清单脚本"
  plans
  approve 20260821-141421
  pending
"""

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>多Agent工作台</title>
<style>
  :root {
    --bg: #171717;
    --panel: #202020;
    --panel-2: #2c2c2c;
    --panel-3: #323232;
    --line: #343434;
    --line-soft: #292929;
    --text: #e1e1e1;
    --muted: #a0a0a0;
    --faint: #747474;
    --accent: #d7d7d7;
    --ok: #8fd7c7;
    --bad: #ff9b8d;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    overflow: hidden;
    background: var(--bg);
    color: var(--text);
    font-family: "Segoe UI", "Microsoft YaHei UI", Arial, sans-serif;
    letter-spacing: 0;
  }
  button, input { font: inherit; }
  button { color: inherit; }
  .windowbar {
    height: 54px;
    border-bottom: 1px solid #202020;
    background: #202020;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 18px;
    color: #a7a7a7;
    user-select: none;
  }
  .window-left,
  .window-menu,
  .window-controls {
    display: flex;
    align-items: center;
    gap: 24px;
  }
  .window-icon {
    width: 18px;
    height: 18px;
    color: #9b9b9b;
    display: grid;
    place-items: center;
    font-size: 18px;
    line-height: 1;
  }
  .window-menu {
    gap: 36px;
    color: #9c9c9c;
    font-size: 18px;
    font-weight: 600;
  }
  .window-controls {
    gap: 28px;
    color: #f0f0f0;
    font-size: 18px;
  }
  .app {
    height: calc(100vh - 54px);
    display: grid;
    grid-template-columns: 364px minmax(0, 1fr) 452px;
    background: var(--bg);
  }
  body.right-collapsed .app {
    grid-template-columns: 364px minmax(0, 1fr) 0;
  }
  body.left-collapsed .app {
    grid-template-columns: 0 minmax(0, 1fr) 452px;
  }
  body.left-collapsed.right-collapsed .app {
    grid-template-columns: 0 minmax(0, 1fr) 0;
  }
  .sidebar {
    min-width: 0;
    border-right: 1px solid var(--line);
    background: #1f1f1f;
    padding: 18px 11px 14px;
    display: flex;
    flex-direction: column;
  }
  .brand {
    height: 38px;
    display: flex;
    align-items: center;
    padding: 0 12px;
    gap: 8px;
    font-size: 26px;
    font-weight: 700;
    color: #d9d9d9;
  }
  .brand small {
    color: var(--muted);
    font-size: 12px;
    font-weight: 600;
  }
  .side-actions {
    display: grid;
    gap: 2px;
    margin: 20px 0 32px;
  }
  .side-button,
  .project-row,
  .recent-row {
    width: 100%;
    min-height: 42px;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: #c8c8c8;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    text-align: left;
    cursor: pointer;
    font-size: 17px;
  }
  .nav-ico {
    width: 24px;
    color: #c6c6c6;
    display: inline-grid;
    place-items: center;
    font-size: 19px;
  }
  .side-button:hover,
  .project-row:hover,
  .recent-row:hover { background: #282828; }
  .side-button:disabled,
  .project-row:disabled,
  .recent-row:disabled,
  .share-button:disabled,
  .location-button:disabled {
    cursor: default;
  }
  .side-button:disabled:hover,
  .project-row:disabled:hover,
  .recent-row:disabled:hover { background: transparent; }
  .project-row.active {
    background: #333333;
    color: #f0f0f0;
  }
  .project-row.sub {
    padding-left: 48px;
    min-height: 34px;
    font-size: 15px;
  }
  .project-row.muted {
    color: #7a7a7a;
  }
  .section-label {
    margin: 0 12px 8px;
    color: #898989;
    font-size: 16px;
    font-weight: 650;
  }
  .project-list,
  .recent-list {
    display: grid;
    gap: 2px;
    margin-bottom: 24px;
  }
  .project-row,
  .recent-row {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .recent-list {
    min-height: 0;
    overflow: hidden;
  }
  .spacer { flex: 1; min-height: 12px; }
  .userbar {
    border-top: 1px solid var(--line);
    padding: 12px;
    color: var(--muted);
    font-size: 14px;
  }
  .main {
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .topbar {
    height: 68px;
    border-bottom: 1px solid var(--line);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 22px;
    background: #191919;
  }
  .title {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
    font-size: 20px;
    font-weight: 650;
  }
  .title span:last-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .top-actions { display: flex; align-items: center; gap: 8px; color: #d2d2d2; }
  .top-ellipsis {
    color: #888;
    font-size: 22px;
    margin-left: 2px;
  }
  .ghost-button {
    min-height: 34px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #222;
    padding: 6px 12px;
    cursor: pointer;
  }
  .icon-button {
    width: 42px;
    height: 42px;
    border: 0;
    border-radius: 12px;
    background: #242424;
    color: #d9d9d9;
    display: grid;
    place-items: center;
    cursor: pointer;
  }
  .icon-button:hover { background: #303030; }
  .icon-button:focus-visible {
    outline: 1px solid #d0d0d0;
    outline-offset: 0;
  }
  .icon-button[aria-pressed="false"] {
    color: #777;
    background: #1f1f1f;
  }
  .icon {
    position: relative;
    width: 17px;
    height: 17px;
    display: block;
  }
  .icon-controls::before,
  .icon-controls::after {
    content: "";
    position: absolute;
    left: 3px;
    right: 3px;
    height: 1.6px;
    border-radius: 1px;
    background: currentColor;
  }
  .icon-controls::before { top: 5px; }
  .icon-controls::after { bottom: 5px; }
  .icon-controls span::before,
  .icon-controls span::after {
    content: "";
    position: absolute;
    width: 5px;
    height: 5px;
    border: 1.5px solid currentColor;
    border-radius: 50%;
    background: #252525;
  }
  .icon-controls span::before { top: 2px; left: 5px; }
  .icon-controls span::after { bottom: 2px; right: 5px; }
  .icon-terminal::before {
    content: "";
    position: absolute;
    inset: 3px 2px;
    border: 1.6px solid currentColor;
    border-radius: 2px;
  }
  .icon-terminal::after {
    content: "";
    position: absolute;
    left: 5px;
    right: 5px;
    bottom: 5px;
    height: 1.6px;
    border-radius: 1px;
    background: currentColor;
  }
  .icon-sidebar::before {
    content: "";
    position: absolute;
    inset: 2px 3px;
    border: 1.6px solid currentColor;
    border-radius: 3px;
  }
  .icon-sidebar::after {
    content: "";
    position: absolute;
    top: 4px;
    bottom: 4px;
    left: 9px;
    width: 1.6px;
    border-radius: 1px;
    background: currentColor;
  }
  .content {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 74px 0 300px;
  }
  .thread {
    width: min(1104px, calc(100% - 72px));
    margin: 0 auto;
  }
  .event {
    display: grid;
    grid-template-columns: 1fr;
    gap: 14px;
    margin: 24px 0;
  }
  .event-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #9a9a9a;
    font-size: 14px;
  }
  .event-rule {
    height: 1px;
    background: var(--line);
    flex: 1;
  }
  .assistant-text {
    color: #e2e2e2;
    font-size: 15px;
    line-height: 1.75;
  }
  .assistant-text p { margin: 0 0 12px; }
  .user-pill {
    justify-self: end;
    max-width: 68%;
    border-radius: 22px;
    background: #262626;
    padding: 10px 16px;
    color: #eeeeee;
    font-size: 15px;
    line-height: 1.5;
  }
  .resource {
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #202020;
    padding: 16px 18px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
  }
  .resource-main {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .resource-icon {
    width: 52px;
    height: 52px;
    border-radius: 8px;
    background: #111;
    display: grid;
    place-items: center;
    color: #d8d8d8;
    font-size: 14px;
    font-weight: 700;
  }
  .resource-title { font-weight: 650; font-size: 17px; }
  .resource-subtitle { color: var(--muted); font-size: 15px; margin-top: 3px; }
  .inline-progress {
    display: none;
    margin-top: 16px;
  }
  .inline-progress h3 {
    margin: 0 0 10px;
    color: #bdbdbd;
    font-size: 14px;
  }
  .output {
    margin: 0;
    max-height: 184px;
    overflow: auto;
    border: 0;
    background: #111111;
    color: #d7d7d7;
    padding: 8px 14px 12px;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: Consolas, "Courier New", monospace;
    font-size: 13px;
    line-height: 1.45;
  }
  body.output-collapsed .output {
    display: none;
  }
  .output .ok { color: #d7d7d7; }
  .output .err { color: var(--bad); }
  .output .cmdline { color: #f0f0f0; }
  .composer {
    position: fixed;
    left: 364px;
    right: 452px;
    bottom: 0;
    padding: 10px 0 0;
    background: linear-gradient(rgba(23, 23, 23, 0), #171717 28%, #171717);
  }
  body.right-collapsed .composer {
    right: 0;
  }
  body.left-collapsed .composer {
    left: 0;
  }
  .composer-box {
    width: min(1104px, 64%, calc(100% - 72px));
    margin: 0 auto;
    border: 1px solid var(--line);
    border-radius: 26px 26px 0 0;
    background: #2c2c2c;
    box-shadow: 0 18px 52px rgba(0, 0, 0, 0.32);
    padding: 11px 14px 9px;
  }
  .terminal-dock {
    width: 100%;
    margin: 0;
    border: 1px solid var(--line);
    border-top: 0;
    border-radius: 0;
    background: #111111;
    overflow: hidden;
  }
  body.output-collapsed .terminal-dock {
    display: none;
  }
  body.output-collapsed .composer-box {
    border-radius: 26px;
  }
  #goal {
    width: 100%;
    min-height: 38px;
    border: 0;
    outline: none;
    background: transparent;
    color: #f1f1f1;
    padding: 2px 6px;
    font-size: 15px;
  }
  #goal::placeholder { color: #a5a5a5; }
  .composer-actions {
    min-height: 32px;
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--muted);
  }
  .composer-actions .fill {
    flex: 1;
  }
  .small-button {
    min-height: 28px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #303030;
    color: #d8d8d8;
    padding: 4px 8px;
    font-size: 13px;
    cursor: pointer;
  }
  .send-button {
    width: 34px;
    height: 34px;
    border: 0;
    border-radius: 50%;
    background: #ececec;
    color: #151515;
    cursor: pointer;
    font-weight: 700;
  }
  .right-panel {
    min-width: 0;
    border-left: 1px solid var(--line);
    background: #1b1b1b;
    padding: 18px 18px;
  }
  body.right-collapsed .right-panel {
    display: none;
  }
  body.left-collapsed .sidebar {
    display: none;
  }
  .inspector {
    border-radius: 24px;
    background: #2c2c2c;
    padding: 18px;
  }
  .inspector h2 {
    margin: 0;
    color: #bdbdbd;
    font-size: 15px;
  }
  .panel-title-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;
  }
  .panel-title-row h3 {
    margin: 0;
  }
  .panel-plus {
    border: 0;
    background: transparent;
    color: #9b9b9b;
    font-size: 24px;
    line-height: 1;
    cursor: default;
    padding: 0 2px;
  }
  .info-list {
    display: grid;
    gap: 12px;
    padding-bottom: 16px;
    border-bottom: 1px solid #444;
  }
  .info-row {
    display: grid;
    grid-template-columns: 58px minmax(0, 1fr);
    gap: 12px;
    color: #dedede;
    font-size: 14px;
  }
  .info-row span:first-child { color: #9b9b9b; }
  .muted-row { color: #8e8e8e; }
  .panel-section {
    padding-top: 18px;
  }
  .panel-section h3 {
    margin: 0 0 12px;
    color: #9c9c9c;
    font-size: 14px;
  }
  .process {
    border-radius: 8px;
    background: #202020;
    padding: 10px 12px;
    color: #dedede;
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
    line-height: 1.45;
  }
  .source-list {
    display: grid;
    gap: 8px;
  }
  .source-item {
    min-width: 0;
    border-radius: 8px;
    background: #202020;
    color: #bdbdbd;
    padding: 9px 10px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-size: 13px;
  }
  .agent-tree-card {
    border-radius: 8px;
    background: #202020;
    padding: 12px;
  }
  .progress-summary {
    display: grid;
    gap: 6px;
    padding-bottom: 12px;
    border-bottom: 1px solid #363636;
    color: #d8d8d8;
    font-size: 12px;
    line-height: 1.45;
  }
  .progress-summary strong {
    color: #f0f0f0;
    font-weight: 650;
  }
  .agent-tree {
    margin-top: 12px;
    display: grid;
  }
  .agent-node {
    position: relative;
    display: grid;
    grid-template-columns: 18px minmax(0, 1fr);
    gap: 8px;
    min-height: 38px;
    padding-bottom: 12px;
  }
  .agent-node::before {
    content: "";
    position: absolute;
    left: 8px;
    top: 20px;
    bottom: -2px;
    width: 1px;
    background: #4a4a4a;
  }
  .agent-node:last-child::before {
    display: none;
  }
  .agent-dot {
    position: relative;
    z-index: 1;
    width: 17px;
    height: 17px;
    margin-top: 2px;
    border-radius: 50%;
    border: 2px solid #777;
    background: #202020;
  }
  .agent-node.done .agent-dot { border-color: var(--ok); background: var(--ok); }
  .agent-node.waiting .agent-dot { border-color: #d7c78f; background: #554b23; }
  .agent-node.running .agent-dot { border-color: #b9d7ff; background: #23435d; }
  .agent-node.idle .agent-dot { border-color: #696969; }
  .agent-body {
    min-width: 0;
  }
  .agent-label {
    color: #ededed;
    font-size: 13px;
    font-weight: 650;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .agent-meta {
    margin-top: 3px;
    color: #a7a7a7;
    font-size: 11px;
    line-height: 1.35;
  }
  .agent-branches {
    margin: 2px 0 8px 26px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
  .branch-node {
    border: 1px solid #3c3c3c;
    border-radius: 8px;
    background: #242424;
    padding: 7px 8px;
  }
  .branch-node.done { border-color: rgba(143, 215, 199, 0.65); }
  .branch-node .agent-label { font-size: 12px; }
  .tree-empty {
    color: #9c9c9c;
    font-size: 12px;
    line-height: 1.5;
  }
  @media (max-width: 1600px) {
    .app { grid-template-columns: 290px minmax(0, 1fr) 330px; }
    body.right-collapsed .app { grid-template-columns: 290px minmax(0, 1fr) 0; }
    body.left-collapsed .app { grid-template-columns: 0 minmax(0, 1fr) 330px; }
    body.left-collapsed.right-collapsed .app { grid-template-columns: 0 minmax(0, 1fr) 0; }
    .composer { left: 290px; right: 330px; }
    body.right-collapsed .composer { right: 0; }
    body.left-collapsed .composer { left: 0; }
    .thread { width: min(960px, calc(100% - 48px)); }
    .composer-box { width: min(960px, 64%, calc(100% - 48px)); }
    .terminal-dock { width: 100%; }
    .side-button, .project-row, .recent-row { font-size: 15px; min-height: 38px; }
    .section-label { font-size: 13px; }
    .title { font-size: 16px; }
    #goal { font-size: 15px; }
    .assistant-text, .user-pill { font-size: 14px; }
    .resource { padding: 12px 14px; }
    .resource-icon { width: 42px; height: 42px; font-size: 12px; }
    .resource-title { font-size: 15px; }
    .resource-subtitle { font-size: 13px; }
    .info-row { font-size: 13px; }
    .inspector h2 { font-size: 14px; }
    .panel-section h3 { font-size: 14px; }
    .source-item { font-size: 13px; }
    .process { font-size: 12px; }
    .agent-branches { grid-template-columns: 1fr; }
  }
  @media (max-width: 1250px) {
    .app { grid-template-columns: 300px minmax(0, 1fr); }
    .right-panel { display: none; }
    .composer { right: 0; left: 300px; }
    .thread { width: min(900px, calc(100% - 40px)); }
    .composer-box { width: min(900px, 70%, calc(100% - 40px)); }
    .terminal-dock { width: 100%; }
    .inline-progress { display: block; }
  }
  @media (max-width: 760px) {
    .app { grid-template-columns: 1fr; }
    .windowbar { padding: 0 14px; }
    .window-menu { display: none; }
    .window-left,
    .window-controls { gap: 16px; }
    .sidebar { display: none; }
    .topbar { padding: 0 14px; }
    .content { padding: 24px 0 300px; }
    .event { margin: 14px 0; }
    .thread { width: calc(100% - 28px); }
    .composer-box { width: calc(100% - 28px); }
    .terminal-dock { width: 100%; }
    .output { max-height: 96px; }
    .composer { left: 0; right: 0; }
    .user-pill { max-width: 86%; }
  }
</style>
</head>
<body>
<div class="windowbar">
  <div class="window-left">
    <span class="window-icon">▯</span>
    <span class="window-icon">←</span>
    <span class="window-icon">→</span>
    <nav class="window-menu" aria-label="应用菜单">
      <span>文件</span>
      <span>编辑</span>
      <span>视图</span>
      <span>帮助</span>
    </nav>
  </div>
  <div class="window-controls" aria-hidden="true">
    <span>−</span>
    <span>▢</span>
    <span>×</span>
  </div>
</div>
<div class="app">
  <aside class="sidebar">
    <div class="brand">Codex <small>⌄</small></div>
    <div class="side-actions">
      <button class="side-button" data-reset><span class="nav-ico">□</span><span>新对话</span></button>
      <button class="side-button" disabled><span class="nav-ico">⌘</span><span>拉取请求</span></button>
      <button class="side-button" disabled><span class="nav-ico">▦</span><span>站点</span></button>
      <button class="side-button" disabled><span class="nav-ico">◷</span><span>已安排</span></button>
      <button class="side-button" disabled><span class="nav-ico">◎</span><span>插件</span></button>
    </div>

    <div class="section-label">项目</div>
    <div class="project-list">
      <button class="project-row" disabled><span class="nav-ico">□</span><span>c成长</span></button>
      <button class="project-row active"><span class="nav-ico">□</span><span>agent协作</span></button>
      <button class="project-row sub" data-fill='run "整理项目功能与推进计划"'>梳理项目功能与推进计划</button>
      <button class="project-row sub" data-fill='start "生成任务上下文"'>看看这个项目</button>
      <button class="project-row sub" data-command='demo "演示基础闭环"'>解释版本编号规则</button>
      <button class="project-row sub muted" disabled>展开显示</button>
      <button class="project-row" disabled><span class="nav-ico">□</span><span>幼儿园网站</span></button>
      <button class="project-row" disabled><span class="nav-ico">□</span><span>学习</span></button>
    </div>

    <div class="section-label">最近</div>
    <div class="recent-list">
      <button class="recent-row" disabled>翻译内容</button>
      <button class="recent-row" disabled>制定工具台工作规则</button>
      <button class="recent-row" disabled>规范项目文件整理</button>
      <button class="recent-row" disabled>检查 dsh 是否删干净</button>
    </div>
    <div class="spacer"></div>
    <div class="userbar">本机模式 · 主知识库只读</div>
  </aside>

  <main class="main">
    <header class="topbar">
      <div class="title"><span>□</span><span>梳理项目功能与推进计划</span><span class="top-ellipsis">···</span></div>
      <div class="top-actions">
        <button class="icon-button" id="toggleRightPanel" title="显示或收起环境信息" aria-label="显示或收起环境信息" aria-pressed="true"><span class="icon icon-controls"><span></span></span></button>
        <button class="icon-button" id="toggleOutput" title="显示或收起运行输出" aria-label="显示或收起运行输出" aria-pressed="true"><span class="icon icon-terminal"></span></button>
        <button class="icon-button" id="toggleLeftPanel" title="显示或收起左侧导航" aria-label="显示或收起左侧导航" aria-pressed="true"><span class="icon icon-sidebar"></span></button>
      </div>
    </header>

    <section class="content" id="content">
      <div class="thread" id="thread">
        <div class="event">
          <div class="user-pill">打开给我看看</div>
        </div>
        <div class="event">
          <div class="event-meta"><span>就绪</span><span class="event-rule"></span></div>
          <div class="assistant-text">
            <p>软件页面已打开。未实现的功能位置先留空，只保留当前能运行的输入和命令。</p>
            <div class="inline-progress">
              <h3>Agent 关系与进度</h3>
              <div class="agent-tree-card">
                <div class="progress-summary" id="progressSummaryInline">
                  <div><strong>最近任务</strong>：读取中</div>
                  <div><strong>状态</strong>：读取中</div>
                </div>
                <div class="agent-tree" id="agentTreeInline">
                  <div class="tree-empty">正在读取本地方案和工作流日志。</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="composer">
      <div class="composer-box">
        <input id="goal" autocomplete="off" spellcheck="false" placeholder="输入任务，例如：给候选记录增加搜索">
        <div class="composer-actions">
          <button class="small-button" data-fill='pending'>候选</button>
          <button class="small-button" data-fill='plans'>方案</button>
          <button class="small-button" data-fill='review'>审查</button>
          <button class="small-button" id="startOnly">只生成上下文</button>
          <span class="fill"></span>
          <button class="send-button" id="runTask" title="运行工作流">↑</button>
        </div>
      </div>
      <div class="terminal-dock">
        <pre class="output" id="output">&gt; provider
当前 Provider：mock
模型：mock-model
接口地址：本地模拟，不联网
密钥环境变量：未配置
密钥状态：未配置
可用 Provider：mock, deepseek, openai, openai-compatible
切换示例：$env:AGENT_WORKBENCH_PROVIDER='deepseek'</pre>
      </div>
    </section>
  </main>

  <aside class="right-panel">
    <div class="inspector">
      <div class="panel-title-row">
        <h2>环境信息</h2>
        <button class="panel-plus" aria-label="添加环境信息" title="添加环境信息">+</button>
      </div>
      <div class="info-list">
        <div class="info-row"><span>▣</span><strong>变更</strong></div>
        <div class="info-row"><span>▭</span><strong>本地</strong></div>
        <div class="info-row"><span>⌘</span><strong>master</strong></div>
        <div class="info-row muted-row"><span>—</span><strong>提交或推送</strong></div>
        <div class="info-row muted-row"><span>◉</span><strong>无法获取拉取请求状态</strong></div>
      </div>
      <div class="panel-section">
        <h3>Agent 关系与进度</h3>
        <div class="agent-tree-card">
          <div class="progress-summary" id="progressSummary">
            <div><strong>最近任务</strong>：读取中</div>
            <div><strong>状态</strong>：读取中</div>
          </div>
          <div class="agent-tree" id="agentTree">
            <div class="tree-empty">正在读取本地方案和工作流日志。</div>
          </div>
        </div>
      </div>
      <div class="panel-section">
        <h3>后台进程</h3>
        <div class="process" id="lastCommand">$env:PYTHONPATH='src'; python -m code_agent_collab.webui</div>
      </div>
      <div class="panel-section">
        <div class="panel-title-row">
          <h3>来源</h3>
          <button class="panel-plus" aria-label="添加来源" title="添加来源">+</button>
        </div>
        <div class="source-list">
          <div class="source-item">src/code_agent_collab/webui.py</div>
          <div class="source-item">tests/test_webui.py</div>
          <div class="source-item">变更记录.md</div>
        </div>
      </div>
    </div>
  </aside>
</div>
<script>
  const output = document.getElementById("output");
  const goalInput = document.getElementById("goal");
  const runStatus = document.getElementById("runStatus");
  const lastCommand = document.getElementById("lastCommand");
  const providerText = document.getElementById("providerText");
  const progressSummary = document.getElementById("progressSummary");
  const agentTree = document.getElementById("agentTree");
  const progressSummaryInline = document.getElementById("progressSummaryInline");
  const agentTreeInline = document.getElementById("agentTreeInline");

  function setText(node, text) {
    if (node) node.textContent = text;
  }

  function append(text, className = "out") {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = text;
    output.appendChild(document.createTextNode("\\n"));
    output.appendChild(span);
    output.scrollTop = output.scrollHeight;
  }

  function quoteArg(text) {
    return `"${String(text).replace(/\\\\/g, "\\\\\\\\").replace(/"/g, "\\\\\\"")}"`;
  }

  async function run(command) {
    if (!command.trim()) return;
    setText(runStatus, "运行中");
    setText(lastCommand, command);
    append(`> ${command}`, "cmdline");
    try {
      const resp = await fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        append(data.error || "请求失败", "err");
        setText(runStatus, "失败");
        return;
      }
      append(data.output || "命令已完成。", data.code === 0 ? "out" : "err");
      setText(runStatus, data.code === 0 ? "完成" : "失败");
      if (command === "provider" && data.output) {
        const match = data.output.match(/当前 Provider：(.+)/);
        if (match) setText(providerText, match[1].trim());
      }
      refreshProgress();
    } catch (e) {
      append(`网络错误：${String(e)}`, "err");
      setText(runStatus, "失败");
    }
  }

  function fill(command) {
    goalInput.value = command;
    goalInput.focus();
  }

  function statusText(status) {
    return {
      done: "已完成",
      waiting: "等待人工",
      running: "进行中",
      idle: "未开始",
    }[status] || status;
  }

  function renderAgentNode(node) {
    const wrap = document.createElement("div");
    wrap.className = `agent-node ${node.status}`;
    const dot = document.createElement("span");
    dot.className = "agent-dot";
    const body = document.createElement("div");
    body.className = "agent-body";
    const label = document.createElement("div");
    label.className = "agent-label";
    label.textContent = node.label;
    const meta = document.createElement("div");
    meta.className = "agent-meta";
    meta.textContent = `${statusText(node.status)} · ${node.detail}`;
    body.appendChild(label);
    body.appendChild(meta);
    wrap.appendChild(dot);
    wrap.appendChild(body);
    return wrap;
  }

  function appendSummaryLine(container, label, value) {
    const line = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = label;
    line.appendChild(strong);
    line.appendChild(document.createTextNode(`：${value}`));
    container.appendChild(line);
  }

  function renderProgressTarget(summaryNode, treeNode, data) {
    const plan = data.latest_plan;
    const workflow = data.latest_workflow;
    summaryNode.innerHTML = "";
    appendSummaryLine(summaryNode, "最近任务", plan ? plan.goal : "暂无方案");
    appendSummaryLine(
      summaryNode,
      "状态",
      `${plan ? plan.status : "未开始"}${workflow ? ` · 日志 ${workflow.task_id}` : ""}`
    );

    treeNode.innerHTML = "";
    if (!data.nodes || data.nodes.length === 0) {
      const empty = document.createElement("div");
      empty.className = "tree-empty";
      empty.textContent = "暂无可展示的 Agent 进度。先运行 run 或 run-adaptive。";
      treeNode.appendChild(empty);
      return;
    }
    data.nodes.forEach((node) => {
      if (node.kind === "branch") {
        const branch = document.createElement("div");
        branch.className = "agent-branches";
        node.children.forEach((child) => {
          const item = document.createElement("div");
          item.className = `branch-node ${child.status}`;
          const label = document.createElement("div");
          label.className = "agent-label";
          label.textContent = child.label;
          const meta = document.createElement("div");
          meta.className = "agent-meta";
          meta.textContent = `${statusText(child.status)} · ${child.detail}`;
          item.appendChild(label);
          item.appendChild(meta);
          branch.appendChild(item);
        });
        treeNode.appendChild(branch);
        return;
      }
      treeNode.appendChild(renderAgentNode(node));
    });
  }

  function renderProgress(data) {
    renderProgressTarget(progressSummary, agentTree, data);
    renderProgressTarget(progressSummaryInline, agentTreeInline, data);
  }

  async function refreshProgress() {
    try {
      const resp = await fetch("/api/progress");
      const data = await resp.json();
      if (resp.ok) renderProgress(data);
    } catch (e) {
      agentTree.innerHTML = '<div class="tree-empty">进度读取失败。</div>';
    }
  }

  document.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", () => run(button.dataset.command));
  });
  document.querySelectorAll("[data-fill]").forEach((button) => {
    button.addEventListener("click", () => fill(button.dataset.fill));
  });
  document.querySelectorAll("[data-reset]").forEach((button) => {
    button.addEventListener("click", () => {
      goalInput.value = "";
      output.textContent = "> provider\\n当前 Provider：mock\\n模型：mock-model\\n接口地址：本地模拟，不联网\\n密钥环境变量：未配置\\n密钥状态：未配置\\n可用 Provider：mock, deepseek, openai, openai-compatible\\n切换示例：$env:AGENT_WORKBENCH_PROVIDER='deepseek'";
      setText(runStatus, "未运行");
      setText(lastCommand, "$env:PYTHONPATH='src'; python -m code_agent_collab.webui");
      goalInput.focus();
    });
  });
  document.getElementById("runTask").addEventListener("click", () => {
    const goal = goalInput.value.trim();
    if (!goal) return;
    if (/^(pending|plans|review|provider|help|confirm|discard|demo|start|run)\\b/.test(goal)) {
      run(goal);
    } else {
      run(`run ${quoteArg(goal)}`);
    }
  });
  document.getElementById("toggleLeftPanel").addEventListener("click", (event) => {
    document.body.classList.toggle("left-collapsed");
    event.currentTarget.setAttribute(
      "aria-pressed",
      String(!document.body.classList.contains("left-collapsed"))
    );
  });
  document.getElementById("toggleOutput").addEventListener("click", (event) => {
    document.body.classList.toggle("output-collapsed");
    event.currentTarget.setAttribute(
      "aria-pressed",
      String(!document.body.classList.contains("output-collapsed"))
    );
  });
  document.getElementById("toggleRightPanel").addEventListener("click", (event) => {
    document.body.classList.toggle("right-collapsed");
    event.currentTarget.setAttribute(
      "aria-pressed",
      String(!document.body.classList.contains("right-collapsed"))
    );
  });
  document.getElementById("startOnly").addEventListener("click", () => {
    const goal = goalInput.value.trim();
    if (goal) run(`start ${quoteArg(goal)}`);
  });
  goalInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") document.getElementById("runTask").click();
  });
  refreshProgress();
</script>
</body>
</html>
"""

_ACTIVE_PROCESSES: set[subprocess.Popen] = set()


def _kill_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            process.terminate()
            process.wait(timeout=3)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        try:
            process.wait(timeout=3)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            process.kill()
        except OSError:
            pass
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _shutdown_cleanup() -> None:
    for process in list(_ACTIVE_PROCESSES):
        _kill_process_tree(process)


atexit.register(_shutdown_cleanup)


def build_command(text: str) -> list[str]:
    args = shlex.split(text)
    if not args:
        raise ValueError("命令为空")
    if args[0] not in ALLOWED_COMMANDS:
        raise ValueError(f"不允许的命令：{args[0]}（可用：{', '.join(sorted(ALLOWED_COMMANDS))}）")
    return args


def run_cli(args: list[str], timeout: int = 180) -> tuple[int, str]:
    if args[0] == "help":
        return 0, HELP_TEXT
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        # 打包模式：调用同目录的 CLI 可执行程序（PyInstaller 单文件模式无法 -m 启动）
        cli_exe = Path(sys.executable).resolve().parent / CLI_EXE_NAME
        command = [str(cli_exe), *args]
    else:
        env["PYTHONPATH"] = str(SRC_DIR)
        command = [sys.executable, "-m", "code_agent_collab.cli", *args]
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    _ACTIVE_PROCESSES.add(process)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        process.wait()
        raise
    finally:
        _ACTIVE_PROCESSES.discard(process)
    output = stdout
    if stderr:
        output += "\n" + stderr
    return process.returncode, output


def _latest_path(folder: Path, pattern: str) -> Path | None:
    if not folder.exists():
        return None
    matches = sorted(folder.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _node(label: str, status: str, detail: str) -> dict:
    return {"kind": "node", "label": label, "status": status, "detail": detail}


def _role_counts(workflow_path: Path | None) -> dict[str, int]:
    if workflow_path is None or not workflow_path.exists():
        return {}
    content = workflow_path.read_text(encoding="utf-8", errors="replace")
    counts: dict[str, int] = {}
    for role in re.findall(r"^##\s+([A-Za-z]+Agent)\s*$", content, flags=re.MULTILINE):
        counts[role] = counts.get(role, 0) + 1
    return counts


def _consume_role(counts: dict[str, int], role: str) -> bool:
    value = counts.get(role, 0)
    if value <= 0:
        return False
    counts[role] = value - 1
    return True


def _plan_snapshot(plan_path: Path | None, workflow_path: Path | None) -> tuple[dict | None, list[dict]]:
    if plan_path is None:
        return None, []
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    task_id = data["task_id"]
    workflow_done = workflow_path is not None and workflow_path.name == f"{task_id}-adaptive.md"
    status = "已执行" if workflow_done else "待批准"
    plan = {
        "task_id": task_id,
        "goal": data.get("goal", ""),
        "status": status,
        "complexity": data.get("complexity", ""),
        "label": data.get("label", ""),
        "worker_count": data.get("worker_count", 0),
    }

    counts = _role_counts(workflow_path if workflow_done else None)
    nodes = [
        _node("ContextPack", "done", "生成任务上下文包"),
        _node("OrchestratorAgent", "done", f"{plan['complexity']} · {plan['label']}"),
        _node("人工审批", "done" if workflow_done else "waiting", "approve 后才执行 worker"),
    ]
    for stage_index, stage in enumerate(data.get("stages", []), start=1):
        children = []
        for item in stage:
            role = item[0]
            label = item[1]
            done = _consume_role(counts, role)
            node_label = role if not label else f"{role}({label})"
            children.append(
                {
                    "kind": "node",
                    "label": node_label,
                    "status": "done" if done else "idle",
                    "detail": f"阶段 {stage_index}",
                }
            )
        if len(children) == 1:
            nodes.append(children[0])
        elif children:
            nodes.append({"kind": "branch", "children": children})
    return plan, nodes


def _workflow_snapshot(workflow_path: Path | None) -> tuple[dict | None, list[dict]]:
    if workflow_path is None:
        return None, []
    content = workflow_path.read_text(encoding="utf-8", errors="replace")
    roles = re.findall(r"^##\s+([A-Za-z]+Agent)\s*$", content, flags=re.MULTILINE)
    task_match = re.search(r"^- 任务ID：(.+)$", content, flags=re.MULTILINE)
    task_id = task_match.group(1).strip() if task_match else workflow_path.stem
    workflow = {"task_id": task_id, "path": str(workflow_path)}
    if not roles:
        return workflow, []
    nodes = [_node("ContextPack", "done", "生成任务上下文包")]
    for role in roles:
        nodes.append(_node(role, "done", "工作流日志已记录"))
    return workflow, nodes


def build_progress_snapshot(project_root: Path = PROJECT_ROOT) -> dict:
    """构建 Web UI 使用的只读进度快照。"""
    plan_path = _latest_path(project_root / "logs" / "plans", "*.json")
    workflow_path = _latest_path(project_root / "logs" / "workflows", "*.md")
    matching_workflow_path = None
    if plan_path is not None:
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        candidate = project_root / "logs" / "workflows" / f"{plan_data['task_id']}-adaptive.md"
        matching_workflow_path = candidate if candidate.exists() else None
    latest_workflow, workflow_nodes = _workflow_snapshot(matching_workflow_path or workflow_path)
    latest_plan, plan_nodes = _plan_snapshot(plan_path, matching_workflow_path)
    if latest_plan is not None:
        latest_workflow, _ = _workflow_snapshot(matching_workflow_path)
    nodes = plan_nodes or workflow_nodes
    return {
        "latest_plan": latest_plan,
        "latest_workflow": latest_workflow,
        "nodes": nodes,
    }


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/progress":
            self._send_json(200, build_progress_snapshot(PROJECT_ROOT))
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/command":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            command = str(body.get("command", "")).strip()
            args = build_command(command)
            code, output = run_cli(args)
            self._send_json(200, {"code": code, "output": output})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except json.JSONDecodeError:
            self._send_json(400, {"error": "请求体不是合法 JSON"})
        except subprocess.TimeoutExpired:
            self._send_json(408, {"error": "命令执行超时"})
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": f"服务器错误：{exc}"})

    def log_message(self, format: str, *args) -> None:  # noqa: A002, N802
        del format, args


def main() -> None:
    parser = argparse.ArgumentParser(description="多Agent工作台 Web 终端")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Web UI: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        # 等服务器就绪后再打开浏览器（打包成软件后双击即用）
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
