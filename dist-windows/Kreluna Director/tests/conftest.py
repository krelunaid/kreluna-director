from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kreluna-shared" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "director-api"))
sys.path.insert(0, str(ROOT / "apps" / "kreluna-agent"))

TEST_DIR = ROOT / "data" / "test"
TEST_DIR.mkdir(parents=True, exist_ok=True)
db_path = TEST_DIR / "test.db"
if db_path.exists():
    db_path.unlink()
os.environ.setdefault("DIRECTOR_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
os.environ.setdefault("DIRECTOR_EVIDENCE_DIR", str(TEST_DIR / "evidence"))
os.environ.setdefault("DIRECTOR_POLICY_PATH", str(ROOT / "policies" / "default.yaml"))
os.environ.setdefault("KRELUNA_ENROLLMENT_CODE", "KRELUNA-TEST-ENROLL")
