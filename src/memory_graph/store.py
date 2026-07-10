from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.atomic_io import atomic_write_json
from src.constants import DATA_DIR


DEFAULT_GRAPH_FILE = Path(DATA_DIR) / "memory_graph.json"


class MemoryGraphStore:
    """Small file-backed progressive graph store."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or DEFAULT_GRAPH_FILE)
        self._state = self._load()

    def add_node(self, node_id: str, *, owner: str, kind: str, label: str, metadata: dict[str, Any] | None = None) -> dict:
        node = {
            "id": str(node_id),
            "owner": str(owner or "default"),
            "kind": str(kind or "unknown"),
            "label": str(label or node_id),
            "metadata": dict(metadata or {}),
            "updated_at": time.time(),
        }
        self._state["nodes"][node["id"]] = node
        self._save()
        return dict(node)

    def add_edge(self, source: str, target: str, *, owner: str, relation: str, metadata: dict[str, Any] | None = None) -> dict:
        edge = {
            "id": f"{source}->{target}:{relation}",
            "owner": str(owner or "default"),
            "source": str(source),
            "target": str(target),
            "relation": str(relation or "related"),
            "metadata": dict(metadata or {}),
            "updated_at": time.time(),
        }
        self._state["edges"][edge["id"]] = edge
        self._save()
        return dict(edge)

    def neighborhood(self, *, owner: str, node_id: str, budget: int = 25) -> dict[str, Any]:
        owner_key = str(owner or "default")
        requested_budget = int(budget or 25)
        budget = max(1, min(requested_budget, 200))
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        start = self._state["nodes"].get(str(node_id))
        if start and start.get("owner") == owner_key:
            nodes[start["id"]] = dict(start)
        candidate_node_ids: set[str] = set(nodes)
        for edge in self._state["edges"].values():
            if edge.get("owner") != owner_key:
                continue
            if edge.get("source") == node_id or edge.get("target") == node_id:
                for endpoint in (edge.get("source"), edge.get("target")):
                    node = self._state["nodes"].get(endpoint)
                    if node and node.get("owner") == owner_key:
                        candidate_node_ids.add(str(endpoint))
        for edge in self._state["edges"].values():
            if len(nodes) >= budget:
                break
            if edge.get("owner") != owner_key:
                continue
            if edge.get("source") == node_id or edge.get("target") == node_id:
                edges.append(dict(edge))
                for endpoint in (edge.get("source"), edge.get("target")):
                    node = self._state["nodes"].get(endpoint)
                    if node and node.get("owner") == owner_key and len(nodes) < budget:
                        nodes[node["id"]] = dict(node)
        effective_edges = edges[:budget]
        proof = {
            "requested_budget": requested_budget,
            "effective_budget": budget,
            "included_nodes": len(nodes),
            "included_edges": len(effective_edges),
            "omitted_nodes": max(0, len(candidate_node_ids) - len(nodes)),
            "truncated": len(candidate_node_ids) > len(nodes) or len(edges) > len(effective_edges),
        }
        return {"nodes": list(nodes.values()), "edges": effective_edges, "budget": budget, "proof": proof}

    def _load(self) -> dict[str, Any]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {"nodes": dict(data.get("nodes") or {}), "edges": dict(data.get("edges") or {})}
        except (OSError, json.JSONDecodeError):
            pass
        return {"nodes": {}, "edges": {}}

    def _save(self) -> None:
        atomic_write_json(str(self.path), self._state, indent=2)
