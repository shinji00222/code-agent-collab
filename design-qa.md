# Design QA

- source visual truth: user-provided screenshot in the 2026-09-04 Codex task, showing a dark terminal with a vertical agent progress tree.
- implementation URL: `http://127.0.0.1:8091/`
- implementation screenshots:
  - `work/agent-terminal-qa/vertical-tree-desktop.png`
  - `work/agent-terminal-qa/vertical-tree-mobile.png`
  - `work/agent-terminal-qa/collab-switch.png`
- viewport: desktop `1280x900`, mobile `390x844`
- density normalization: Playwright screenshots captured at CSS pixel viewport size with system Chrome headless.
- state: ContextPack done, OrchestratorAgent running, approval/Knowledge/Coder/Reviewer/Reflector idle.

## Full-view comparison evidence

- The existing terminal page shell is preserved: top status line, transcript log, quick command buttons, command output, and bottom composer remain in place.
- The workflow visualization changed from the previous diamond/horizontal branch into a vertical dependency tree.
- ContextPack is complete and purple; OrchestratorAgent is the active glowing purple node with the detail `正在分配执行计划`.
- Future nodes are dark/gray: 人工审批, KnowledgeAgent, CoderAgent(A), CoderAgent(B), ReviewerAgent, ReflectorAgent.
- The CoderAgent(A/B) branch is nested under the main flow with dashed connector lines, and ReviewerAgent continues after the coding branch.
- The `开始协同工作` switch sits in the existing quick command row, so the surrounding terminal layout is preserved while giving the user an explicit handoff from planning to multi-agent execution.

## Findings

- P0/P1/P2: none remaining.
- Earlier P2: the selected target was narrowed by the user to "only change the tree; keep everything else." Fixed by limiting implementation to tree CSS/rendering and preserving the surrounding terminal UI.
- Earlier P2: old `.branch-wire` / `.branch-grid` diamond rendering remained when an old preview process was still serving port 8091. Fixed by restarting the exact local Web UI process and re-running browser QA.
- Earlier P3: idle nodes displayed `idle ·` below labels. Fixed so untouched future nodes stay visually quiet like the reference.

## Interaction Evidence

- Browser automation loaded `http://127.0.0.1:8091/`.
- Verified visible `Agent Workbench`, active `OrchestratorAgent`, detail `正在分配执行计划`, `CoderAgent(A)`, `CoderAgent(B)`, and `ReviewerAgent`.
- Verified old diamond selectors `.branch-wire` and `.branch-grid` are absent.
- Verified command input placeholder remains the original `输入命令，或直接写任务目标`, matching the user's "only change the tree" correction.
- Verified plain task input posts `run-adaptive "讨论一个新功能"` instead of `run "..."`.
- Verified clicking `开始协同工作` posts `approve 20260904-qa-switch` using the latest plan id from `/api/progress`.
- Unit tests: `python -m unittest discover -s tests` -> 79 tests passed.
- Whitespace check: `git diff --check` -> no errors.
- Console warnings/errors: none.

final result: passed
