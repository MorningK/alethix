"""初始化 Qdrant Collection 与 payload 索引。

对应 prd/04-data-model.md §4.1（Collection 定义）与 §4.4（payload 索引）。
幂等：已存在时只补建索引，不重建向量数据。

用法：
    uv run python scripts/init_qdrant.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services import qdrant_service  # noqa: E402


def main() -> int:
    settings = get_settings()
    qdrant_service.init_qdrant(settings)

    try:
        created = qdrant_service.ensure_collection(settings)
    except Exception as exc:  # noqa: BLE001
        print(f"初始化失败：{exc}")
        return 1

    action = "已创建" if created else "已存在"
    print(
        f"{action} collection={settings.qdrant_collection} "
        f"dim={settings.embedding_dim} "
        f"indexes={['user_id', 'doc_id', 'chunk_index']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
