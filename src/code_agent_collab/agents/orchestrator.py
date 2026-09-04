from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..providers import AIProvider, create_provider
from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel


class ComplexityLevel(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


@dataclass(frozen=True)
class WorkerSpec:
    """一个 worker 的规格。label 用于区分多个同类 worker（如"模块A"/"模块B"）。"""

    role: str
    label: str = ""


@dataclass(frozen=True)
class OrchestrationPlan:
    """主控选定的执行方案：复杂度 + 模板名 + 阶段列表（每阶段内可并行）。"""

    complexity: ComplexityLevel
    label: str
    stages: tuple[tuple[WorkerSpec, ...], ...]

    @property
    def worker_count(self) -> int:
        return sum(len(stage) for stage in self.stages)


# 半动态三档模板：阶段间串行（尊重 Knowledge -> Coder 的依赖），阶段内可并行
TEMPLATES: dict[ComplexityLevel, OrchestrationPlan] = {
    ComplexityLevel.SIMPLE: OrchestrationPlan(
        complexity=ComplexityLevel.SIMPLE,
        label="单编码 + 评审",
        stages=((WorkerSpec("CoderAgent"),), (WorkerSpec("ReviewerAgent"),)),
    ),
    ComplexityLevel.MEDIUM: OrchestrationPlan(
        complexity=ComplexityLevel.MEDIUM,
        label="检索 + 编码 + 评审",
        stages=(
            (WorkerSpec("KnowledgeAgent"),),
            (WorkerSpec("CoderAgent"),),
            (WorkerSpec("ReviewerAgent"),),
        ),
    ),
    ComplexityLevel.COMPLEX: OrchestrationPlan(
        complexity=ComplexityLevel.COMPLEX,
        label="检索 + 双编码并行 + 评审（4 阶段）",
        stages=(
            (WorkerSpec("KnowledgeAgent"),),
            (WorkerSpec("CoderAgent", "模块A"), WorkerSpec("CoderAgent", "模块B")),
            (WorkerSpec("ReviewerAgent"),),
        ),
    ),
}

SPLIT_SIGNAL_WORDS = (
    "模块",
    "分别",
    "多个",
    "几个",
    "组件",
    "前后端",
    "接口",
    "服务",
    "页面",
    "功能",
    "拆成",
)
TECH_WORDS = (
    "python",
    "javascript",
    "js",
    "web",
    "api",
    "数据库",
    "前端",
    "后端",
    "测试",
    "部署",
    "docker",
    "git",
)


def estimate_complexity(goal: str) -> ComplexityLevel:
    """规则版复杂度判定：任务长度 + 拆分信号词 + 技术词数量打分。"""
    score = 0
    if len(goal) > 24:
        score += 1
    if any(word in goal for word in SPLIT_SIGNAL_WORDS):
        score += 1
    tech_hits = sum(1 for word in TECH_WORDS if word.lower() in goal.lower())
    if tech_hits >= 2:
        score += 1
    if score >= 2:
        return ComplexityLevel.COMPLEX
    if score == 1:
        return ComplexityLevel.MEDIUM
    return ComplexityLevel.SIMPLE


def estimate_complexity_with_provider(goal: str, provider: AIProvider) -> ComplexityLevel:
    """AI 判定复杂度；输出无法解析或调用失败时回退规则版。"""
    try:
        text = provider.complete(
            "你是任务复杂度评估员，只输出 SIMPLE、MEDIUM、COMPLEX 之一，不要解释。",
            f"请评估这个任务适合拆成几个 worker 并行：{goal}",
        )
        cleaned = text.strip().upper()
        for level in ComplexityLevel:
            if level.value.upper() in cleaned:
                return level
    except Exception:  # noqa: BLE001 - 任何失败都回退规则版
        pass
    return estimate_complexity(goal)


def build_plan(complexity: ComplexityLevel) -> OrchestrationPlan:
    return TEMPLATES[complexity]


class OrchestratorAgent(BaseAgent):
    """主控 Agent（半动态）：判定复杂度，从预设模板选择执行方案，不自由发挥。

    升级空间：self.last_plan 保存结构化方案，供 run_adaptive_workflow 读取执行；
    后续可在模板中加入更多角色或阶段，无需改动执行器。
    """

    role = "OrchestratorAgent"
    permission = PermissionLevel.READ_ONLY

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or create_provider()
        self.last_plan: OrchestrationPlan | None = None

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        complexity = estimate_complexity_with_provider(context.task_goal, self.provider)
        plan = build_plan(complexity)
        self.last_plan = plan
        stage_desc = " → ".join(
            "+".join(spec.role if not spec.label else f"{spec.role}({spec.label})" for spec in stage)
            for stage in plan.stages
        )
        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary=f"主控判定复杂度：{complexity.value}，选用模板：{plan.label}，共 {plan.worker_count} 个 worker。",
            evidence=[
                f"任务目标：{context.task_goal}",
                f"复杂度判定来源：{'Provider(' + self.provider.name + ')' if self.provider.name != 'mock' else '规则版'}",
            ],
            outputs=[
                f"复杂度：{complexity.value}",
                f"模板：{plan.label}",
                f"worker 数量：{plan.worker_count}",
                f"执行阶段：{stage_desc}",
            ],
            risks=["模板为预设三档，不按任务自由拆分；复杂度判定可能不准确。"],
            next_steps=["按模板阶段执行 workers；阶段间串行，阶段内可并行。"],
        )
