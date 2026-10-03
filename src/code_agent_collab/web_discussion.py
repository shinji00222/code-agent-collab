from __future__ import annotations

import re
import threading

from .providers import ProviderConfigurationError, create_provider

_DISCUSSION_LOCK = threading.Lock()
_DISCUSSION_HISTORY: list[dict[str, str]] = []
_DISCUSSION_MAX_ITEMS = 14


def clear_discussion() -> None:
    with _DISCUSSION_LOCK:
        _DISCUSSION_HISTORY.clear()


def build_discussion_goal() -> str:
    with _DISCUSSION_LOCK:
        history = list(_DISCUSSION_HISTORY)
    user_messages = [item["content"] for item in history if item["role"] == "user"]
    if not user_messages:
        return ""
    first_goal = user_messages[0].strip()
    supplements = user_messages[1:]
    if not supplements:
        return first_goal
    return first_goal + "\n\n讨论补充：\n" + "\n".join(
        f"- {item.strip()}" for item in supplements if item.strip()
    )


def _looks_like_question(message: str) -> bool:
    question_markers = ("?", "？", "怎么", "为什么", "啥", "什么", "能不能", "可以吗", "是不是", "如何")
    return any(marker in message for marker in question_markers)


def _mock_discussion_reply(message: str, user_count: int) -> str:
    if re.search(r"(模型|provider|Provider|api|API|key|Key|密钥|联网|本地)", message):
        return (
            "当前是 mock Provider，模型名是 mock-model。"
            "这是本地模拟回复，不联网，也不会消耗 API Key。"
            "如果要接真实模型，可以先用 provider 命令查看状态，再配置 deepseek、openai 或 openai-compatible。"
        )
    if _looks_like_question(message):
        return (
            "可以。你直接问问题时，我会先按问题本身回答；如果信息不够，我再告诉你缺什么，"
            "而不是只反问需求。等你觉得聊清楚了，再点“生成主控方案”。"
        )
    if user_count <= 1:
        return (
            "我先确认几个关键点，再生成方案：\n"
            "1. 你希望最终改的是 Web 页面、CLI 流程，还是两者都要？\n"
            "2. 完成标准是什么：能看到对话、能生成方案、能一键开始协同，还是还要保存讨论记录？\n"
            "3. 有没有不能动的部分，比如树状图、Provider 配置、GitHub 上传流程？"
        )
    return (
        "我把你的补充记下了。现在可以继续补充细节；如果目标已经说清楚，"
        "点“生成主控方案”，我会把这轮讨论整理成 OrchestratorAgent 的计划输入。"
    )


def discuss_with_orchestrator(message: str) -> dict[str, str]:
    cleaned = message.strip()
    if not cleaned:
        raise ValueError("讨论内容为空")

    with _DISCUSSION_LOCK:
        _DISCUSSION_HISTORY.append({"role": "user", "content": cleaned})
        user_count = sum(1 for item in _DISCUSSION_HISTORY if item["role"] == "user")
        history = list(_DISCUSSION_HISTORY[-_DISCUSSION_MAX_ITEMS:])

    provider = create_provider()
    if provider.name == "mock":
        reply = _mock_discussion_reply(cleaned, user_count)
    else:
        transcript = "\n".join(
            f"{item['role']}: {item['content']}" for item in history
        )
        try:
            reply = provider.complete(
                (
                    "你是 OrchestratorAgent 的前置需求讨论员。"
                    "你的任务是和用户对话澄清需求，不要写代码，不要批准执行，不要调用其他 Agent。"
                    "用户问问题时必须先正面回答，不要只追问需求；知道答案就给具体答案，"
                    "不知道就明确说不确定并说明还需要什么信息。回答后如有必要，再继续澄清。"
                    "如果信息不足，最多问 3 个关键问题；如果信息足够，先总结目标、约束和验收标准，"
                    "然后提示用户可以点击“生成主控方案”。"
                ),
                f"当前对话：\n{transcript}\n\n请给出下一轮回复。",
            )
        except ProviderConfigurationError as exc:
            reply = f"真实模型还没配置好：{exc}\n可以先用菜单配置 API，或切回 mock 后继续。"
        except Exception as exc:  # noqa: BLE001 - Web UI 需要把 Provider 失败转成可读提示
            reply = f"真实模型调用失败：{exc}\n可以检查网络/API Key，或切回 mock 后继续。"

    with _DISCUSSION_LOCK:
        _DISCUSSION_HISTORY.append({"role": "assistant", "content": reply})
        del _DISCUSSION_HISTORY[:-_DISCUSSION_MAX_ITEMS]

    return {"output": reply, "goal": build_discussion_goal()}
