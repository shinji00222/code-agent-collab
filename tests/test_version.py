from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from code_agent_collab import __version__


class VersionTests(unittest.TestCase):
    def test_package_version_matches_project_metadata(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        metadata = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(__version__, metadata["project"]["version"])


if __name__ == "__main__":
    unittest.main()
