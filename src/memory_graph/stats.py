from __future__ import annotations

from collections import Counter
from typing import Any


def memory_stats(memory_manager: Any, memory_vector: Any = None) -> dict[str, Any]:
    try:
        rows = memory_manager.load_all()
    except Exception:
        rows = []
    rows = rows if isinstance(rows, list) else []
    by_owner = Counter(str(row.get("owner") or "default") for row in rows if isinstance(row, dict))
    by_category = Counter(str(row.get("category") or "uncategorized") for row in rows if isinstance(row, dict))
    by_source = Counter(str(row.get("source") or "unknown") for row in rows if isinstance(row, dict))
    vector = {"healthy": False, "count": 0}
    if memory_vector is not None:
        vector["healthy"] = bool(getattr(memory_vector, "healthy", False))
        try:
            vector["count"] = int(memory_vector.count())
        except Exception:
            vector["count"] = 0
    return {
        "total": len(rows),
        "by_owner": dict(by_owner),
        "by_category": dict(by_category),
        "by_source": dict(by_source),
        "vector": vector,
    }
