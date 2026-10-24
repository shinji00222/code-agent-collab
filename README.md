# Multi-Agent Software Engineering System

[English](README.md) | [简体中文](README.zh-CN.md)

A local-first coding-agent workbench for turning a coding request into a guarded software-engineering loop: understand the repo, plan the work, draft code, review the result, preview the diff, run tests, and only then apply changes.

This project is not about adding more agents for show. The main goal is to make multi-agent coding behave more like a careful engineering workflow.

## What It Does

- Builds task context from project docs and source files.
- Uses planner, coder, reviewer, integrator, and knowledge roles when they are useful.
- Keeps generated drafts in a separate workspace before touching real source files.
- Reviews drafts for path scope, missing sections, risky changes, secrets, and test instructions.
- Supports dry-run diff preview before applying changes.
- Runs tests before local commits when changes are applied.
- Keeps long-term knowledge writes behind explicit user confirmation.
- Uses a local mock provider by default, so a fresh run does not call an external API.

## Current Status

Current version: `v0.19.0` ([Windows preview `v0.19.0-rc.1`](https://github.com/shinji00222/code-agent-collab/releases/tag/v0.19.0-rc.1)). The package is unsigned and may show a SmartScreen warning; final EXE launch acceptance is pending.

Current direction: **Stable Coding Loop -> Hierarchical Context -> Evaluation -> Execution Sandbox Hardening**.

The project is still an experimental prototype, but the main loop is intentionally conservative: draft first, review, preview diff, test, then apply.

## Quick Start

Requires Python 3.11 or newer.

```powershell
git clone https://github.com/shinji00222/code-agent-collab.git
cd code-agent-collab
$env:PYTHONPATH="src"
python -m code_agent_collab.cli provider
python -m code_agent_collab.cli coding-loop "add a tiny test"
python -m code_agent_collab.cli benchmark
```

Test runs use a temporary project copy, strip API credentials from the test environment, and return at most 64 KiB of command output. Web terminal commands are checked against an allowlist at execution time and have a timeout. The Windows preview candidate includes the execution sandbox hardening described in `CHANGELOG.md`; it is unsigned, may show a SmartScreen warning, and has not passed final EXE launch acceptance. The `coding-loop` command above runs in dry-run mode and previews the proposed change. The benchmark command runs its fixed tasks and tests in temporary projects. To apply a reviewed draft, run:

```powershell
python -m code_agent_collab.cli coding-loop "add a tiny test" --apply
```

By default, the project uses the local `mock` provider. Configure DeepSeek, OpenAI, or an OpenAI-compatible provider only when you want real model calls.

On Windows, run a real DeepSeek evaluation with `powershell -ExecutionPolicy Bypass -File scripts/run-deepseek-benchmark.ps1`, then enter the API key at the hidden prompt. The script sets the key only for the current process and restores the previous environment afterward; the key is not passed as a command-line argument or written to benchmark reports.

`benchmark` compares a one-shot Coder with the adaptive multi-agent coding loop on the same 10 isolated tasks. It writes a Markdown summary and JSONL run records under `logs/benchmarks/`. Every task runs in a temporary project; only `src/solution.py` is applied to the isolated test copy, so model drafts cannot edit the fixed test fixture. Run with `--repeats 3` for independent repeats. Provider-reported usage is preferred; character-based token estimates are used only when usage is missing. Response usage may not include all billing for failed or retried requests.

One DeepSeek `deepseek-chat` run (benchmark v1.3, 10 tasks × 3 repeats) scored 30/30 for both single and multi-agent modes. Average usage was 768 vs 1,935 tokens, and average latency was 3.20s vs 4.83s. These are small pure-function tasks: multi-agent did not improve success on this set and used more tokens and time. This does not predict performance on larger repository tasks.
## Main Commands

```powershell
$env:PYTHONPATH="src"
python -m code_agent_collab.cli provider
python -m code_agent_collab.cli start "task goal"
python -m code_agent_collab.cli run-adaptive "task goal"
python -m code_agent_collab.cli plans
python -m code_agent_collab.cli approve "task id or keyword"
python -m code_agent_collab.cli apply-draft "task id or keyword"
python -m code_agent_collab.cli coding-loop "task goal" [--apply]
python -m code_agent_collab.cli benchmark [--mode single|multi|both] [--repeats N]
python -m code_agent_collab.webui
python -m code_agent_collab.desktop
```

## Safety Model

The project separates AI output from real project files by default:

- generated drafts go to `dev-vault/projects`;
- knowledge candidates go to `dev-vault/pending`;
- real source changes require an explicit apply step;
- public config examples are safe to commit, while real local config stays ignored;
- secrets should be passed through environment variables, never committed.

## Project Layout

```text
src/code_agent_collab/   source code
tests/                   automated tests
product-docs/            product notes and design docs
dev-vault/               generated drafts and isolated project knowledge
logs/                    local run logs and progress snapshots
scripts/                 packaging and setup scripts
```

## Documentation

- [中文 README](README.zh-CN.md)
- [Version plan](VERSIONING.md)
- [Changelog](CHANGELOG.md)
- [Maintenance guide](MAINTENANCE.md)
- [Project skills](SKILLS.md)
- [Code simplification plan](product-docs/code-simplification-plan.md)

## Tests

```powershell
$env:PYTHONPATH="src"
python scripts/run-tests.py
```

You can also run the standard unittest discovery command:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```
