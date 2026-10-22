"""Shared limits for output returned from bounded project executions."""

from __future__ import annotations

MAX_COMMAND_OUTPUT_BYTES = 64 * 1024
OUTPUT_TRUNCATION_MARKER = "\n...[输出过长，已截断；仅保留末尾内容]...\n"


def limit_command_output(output: str, max_bytes: int = MAX_COMMAND_OUTPUT_BYTES) -> str:
    """Keep command results bounded while preserving the useful final diagnostics."""
    if max_bytes <= 0:
        raise ValueError("max_bytes 必须大于 0")
    encoded = output.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return output
    marker = OUTPUT_TRUNCATION_MARKER.encode("utf-8")
    if len(marker) >= max_bytes:
        return marker[-max_bytes:].decode("utf-8", errors="ignore")
    tail = encoded[-(max_bytes - len(marker)) :].decode("utf-8", errors="ignore")
    return OUTPUT_TRUNCATION_MARKER + tail
