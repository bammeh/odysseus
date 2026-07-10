from __future__ import annotations

from fastapi import APIRouter, Query

from src.memory_graph.stats import memory_stats
from src.memory_graph.store import MemoryGraphStore


def setup_memory_graph_routes(memory_manager, memory_vector=None, graph: MemoryGraphStore | None = None) -> APIRouter:
    graph = graph or MemoryGraphStore()
    router = APIRouter(tags=["memory-graph"])

    @router.get("/api/memory/stats")
    def stats():
        return memory_stats(memory_manager, memory_vector)

    @router.get("/api/graph/neighborhood")
    def neighborhood(
        owner: str = Query(default="default"),
        node_id: str = Query(...),
        budget: int = Query(default=25),
    ):
        return graph.neighborhood(owner=owner, node_id=node_id, budget=budget)

    return router
