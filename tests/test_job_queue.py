from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab import job_store, web_jobs


def _drain(scheduler: object, timeout: float = 10.0) -> None:
    """等在跑/排队的任务全部结束。

    必须在 `patch.object(web_jobs, "run_cli", ...)` 的作用域**之内**调用：
    否则 patch 一撤，残留的排队任务就会去跑真实 CLI（会真的改项目、很慢）。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(job.finished for job in scheduler.snapshot()):  # type: ignore[attr-defined]
            return
        time.sleep(0.02)
    raise AssertionError("队列未在超时内排空：残留任务会在 patch 结束后执行真实 CLI")


class JobStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _record(self, job_id: str, status: str = "done", created_at: str = "") -> dict:
        return {
            "job_id": job_id,
            "command": "help",
            "status": status,
            "created_at": created_at or f"2026-10-04T10:00:0{job_id}.000",
            "updated_at": "2026-10-04T10:00:00.000",
            "done": status in {"done", "failed", "timeout", "interrupted"},
        }

    def test_save_and_load_round_trip(self) -> None:
        job_store.save_job(self.root, self._record("a"))
        loaded = job_store.load_job(self.root, "a")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["job_id"], "a")
        self.assertEqual(loaded["status"], "done")

    def test_save_requires_job_id(self) -> None:
        with self.assertRaises(ValueError):
            job_store.save_job(self.root, {"command": "help"})

    def test_load_missing_returns_none(self) -> None:
        self.assertIsNone(job_store.load_job(self.root, "nope"))

    def test_list_is_newest_first(self) -> None:
        for index, job_id in enumerate(("a", "b", "c")):
            job_store.save_job(self.root, self._record(job_id, created_at=f"2026-10-04T10:00:0{index}.000"))
        ids = [item["job_id"] for item in job_store.list_jobs(self.root)]
        self.assertEqual(ids, ["c", "b", "a"])

    def test_list_on_missing_dir_returns_empty(self) -> None:
        self.assertEqual(job_store.list_jobs(self.root), [])

    def test_prune_keeps_newest(self) -> None:
        for index in range(5):
            job_store.save_job(
                self.root,
                self._record(str(index), created_at=f"2026-10-04T10:00:0{index}.000"),
            )
        removed = job_store.prune_jobs(self.root, keep=2)
        self.assertEqual(removed, 3)
        remaining = [item["job_id"] for item in job_store.list_jobs(self.root)]
        self.assertEqual(remaining, ["4", "3"])

    def test_recover_marks_unfinished_as_interrupted(self) -> None:
        job_store.save_job(self.root, self._record("q", status="queued"))
        job_store.save_job(self.root, self._record("r", status="running"))
        job_store.save_job(self.root, self._record("d", status="done"))

        recovered = job_store.recover_interrupted_jobs(self.root, now="2026-10-04T11:00:00.000")

        self.assertEqual(sorted(recovered), ["q", "r"])
        assert job_store.load_job(self.root, "q") is not None
        assert job_store.load_job(self.root, "r") is not None
        assert job_store.load_job(self.root, "d") is not None
        self.assertEqual(job_store.load_job(self.root, "q")["status"], "interrupted")
        self.assertEqual(job_store.load_job(self.root, "r")["status"], "interrupted")
        self.assertTrue(job_store.load_job(self.root, "r")["done"])
        self.assertEqual(job_store.load_job(self.root, "r")["updated_at"], "2026-10-04T11:00:00.000")
        # 已完成的记录不能被改动
        self.assertEqual(job_store.load_job(self.root, "d")["status"], "done")

    def test_recover_does_not_create_directory(self) -> None:
        """没有历史目录时不能顺手建一个（否则每次起服务都凭空多出目录）。"""
        self.assertEqual(job_store.recover_interrupted_jobs(self.root), [])
        self.assertFalse(job_store.jobs_dir(self.root).exists())

    def test_recover_is_idempotent(self) -> None:
        job_store.save_job(self.root, self._record("q", status="queued"))
        self.assertEqual(job_store.recover_interrupted_jobs(self.root), ["q"])
        self.assertEqual(job_store.recover_interrupted_jobs(self.root), [])

    def test_is_finished(self) -> None:
        for status in ("done", "failed", "timeout", "interrupted"):
            self.assertTrue(job_store.is_finished(status))
        for status in ("queued", "running"):
            self.assertFalse(job_store.is_finished(status))


class SchedulerTests(unittest.TestCase):
    """直接测调度器实例，避免模块级单例在不同用例之间串状态。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = str(Path(self._tmp.name) / "project")
        Path(self.root).mkdir()
        self._patches = [
            patch.object(web_jobs, "PROJECT_ROOT", self.root),
        ]
        for item in self._patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self._patches):
            item.stop()
        self._tmp.cleanup()

    def test_duplicate_command_returns_same_job(self) -> None:
        release = threading.Event()
        started: list[str] = []
        gate = threading.Event()

        def fake_run_cli(args, timeout=180):  # noqa: ANN001, ANN202
            started.append(args[0])
            gate.set()
            release.wait(timeout=5)
            return 0, "ok"

        scheduler = web_jobs._JobScheduler()
        with patch.object(web_jobs, "run_cli", side_effect=fake_run_cli):
            first, dup_first = scheduler.submit("run \"任务A\"")
            self.assertFalse(dup_first)
            self.assertTrue(gate.wait(5))
            second, dup_second = scheduler.submit("run \"任务A\"")
            self.assertTrue(dup_second)
            self.assertEqual(first.id, second.id)
            release.set()
            _drain(scheduler)
            self.assertEqual(started, ["run"])

    def test_request_id_dedupes_different_commands(self) -> None:
        release = threading.Event()
        gate = threading.Event()

        def fake_run_cli(args, timeout=180):  # noqa: ANN001, ANN202
            gate.set()
            release.wait(timeout=5)
            return 0, "ok"

        scheduler = web_jobs._JobScheduler()
        with patch.object(web_jobs, "run_cli", side_effect=fake_run_cli):
            first, _ = scheduler.submit("run \"任务B\"", request_id="req-1")
            self.assertTrue(gate.wait(5))
            second, duplicated = scheduler.submit("run \"任务C\"", request_id="req-1")
            self.assertTrue(duplicated)
            self.assertEqual(first.id, second.id)
            release.set()
            _drain(scheduler)

    def test_dedupe_does_not_apply_after_finish(self) -> None:
        scheduler = web_jobs._JobScheduler()
        with patch.object(web_jobs, "run_cli", return_value=(0, "ok")):
            first, _ = scheduler.submit("help")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not scheduler.get(first.id)["done"]:
                time.sleep(0.02)
            self.assertTrue(scheduler.get(first.id)["done"])
            second, duplicated = scheduler.submit("help")
        self.assertFalse(duplicated)
        self.assertNotEqual(first.id, second.id)

    def test_queue_full_raises(self) -> None:
        release = threading.Event()
        scheduler = web_jobs._JobScheduler()

        def fake_run_cli(args, timeout=180):  # noqa: ANN001, ANN202
            release.wait(timeout=10)
            return 0, "ok"

        with patch.object(web_jobs, "run_cli", side_effect=fake_run_cli):
            raised = False
            accepted = 0
            for index in range(20):
                try:
                    scheduler.submit(f'run "任务{index}"')
                    accepted += 1
                except web_jobs.JobQueueFull:
                    raised = True
                    break
            release.set()
            _drain(scheduler)
        self.assertTrue(raised, "队列满时应当抛 JobQueueFull")
        # 上限 = 最多 2 个在跑 + 8 个排队
        self.assertLessEqual(accepted, web_jobs.MAX_ACTIVE_JOBS + web_jobs.MAX_QUEUED_JOBS)

    def test_read_only_commands_can_run_concurrently(self) -> None:
        release = threading.Event()
        gate = threading.Event()
        started: list[str] = []

        def fake_run_cli(args, timeout=180):  # noqa: ANN001, ANN202
            started.append(args[0])
            if len(started) >= 2:
                gate.set()
            release.wait(timeout=10)
            return 0, "ok"

        scheduler = web_jobs._JobScheduler()
        with patch.object(web_jobs, "run_cli", side_effect=fake_run_cli):
            scheduler.submit("plans")
            scheduler.submit("provider")
            self.assertTrue(gate.wait(5), "两个只读命令应当能同时开始")
            self.assertIn("plans", started)
            self.assertIn("provider", started)
            release.set()
            _drain(scheduler)

    def test_write_commands_are_serialised(self) -> None:
        release = threading.Event()
        first_started = threading.Event()
        started: list[str] = []

        def fake_run_cli(args, timeout=180):  # noqa: ANN001, ANN202
            started.append(args[1] if len(args) > 1 else args[0])
            first_started.set()
            release.wait(timeout=10)
            return 0, "ok"

        scheduler = web_jobs._JobScheduler()
        with patch.object(web_jobs, "run_cli", side_effect=fake_run_cli):
            scheduler.submit('run "写任务1"')
            self.assertTrue(first_started.wait(5))
            scheduler.submit('run "写任务2"')
            time.sleep(0.4)
            self.assertEqual(len(started), 1, "写命令最多同时跑一个")
            release.set()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and len(started) < 2:
                time.sleep(0.02)
            self.assertEqual(len(started), 2)
            _drain(scheduler)


class PublicJobApiTests(unittest.TestCase):
    """模块级单例的对外行为：落盘、历史查询、从磁盘补读。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = str(Path(self._tmp.name) / "project")
        Path(self.root).mkdir()
        self._patch = patch.object(web_jobs, "PROJECT_ROOT", self.root)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _wait_done(self, job_id: str, timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        payload = None
        while time.monotonic() < deadline:
            payload = web_jobs.get_command_job(job_id)
            if payload and payload["done"]:
                return payload
            time.sleep(0.02)
        raise AssertionError(f"任务未在 {timeout}s 内结束：{payload}")

    def test_finished_job_is_persisted(self) -> None:
        job = web_jobs.start_command_job("help")
        self.assertFalse(job["deduplicated"])
        self.assertEqual(job["status"], "queued")

        finished = self._wait_done(job["job_id"])

        self.assertEqual(finished["status"], "done")
        stored = job_store.load_job(Path(self.root), job["job_id"])
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["status"], "done")
        self.assertIn("可用命令", stored["output"])

    def test_history_survives_restart(self) -> None:
        """内存里没有的记录，也要能从磁盘查出来（模拟服务重启后的历史查询）。"""
        record = {
            "job_id": "history-1",
            "command": "plans",
            "status": "interrupted",
            "created_at": "2026-10-04T09:00:00.000",
            "updated_at": "2026-10-04T09:00:00.000",
            "done": True,
        }
        job_store.save_job(Path(self.root), record)

        fetched = web_jobs.get_command_job("history-1")
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched["status"], "interrupted")

        listed = web_jobs.list_command_jobs()
        self.assertIn("history-1", [item["job_id"] for item in listed])

    def test_initialise_job_history_marks_interrupted(self) -> None:
        job_store.save_job(
            Path(self.root),
            {
                "job_id": "leftover",
                "command": "run \"x\"",
                "status": "running",
                "created_at": "2026-10-04T08:00:00.000",
                "updated_at": "2026-10-04T08:00:00.000",
                "done": False,
            },
        )
        recovered = web_jobs.initialise_job_history()
        self.assertEqual(recovered, ["leftover"])
        stored = job_store.load_job(Path(self.root), "leftover")
        assert stored is not None
        self.assertEqual(stored["status"], "interrupted")
        self.assertTrue(stored["done"])


if __name__ == "__main__":
    unittest.main()
