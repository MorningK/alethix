"""worker 包入口：uv run python -m workers"""

from __future__ import annotations

from workers.ingest_worker import main

if __name__ == "__main__":
    main()
