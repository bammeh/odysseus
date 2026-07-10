from __future__ import annotations

from fastapi import APIRouter, Query, Request

from src.memory_graph.maintenance import MemoryMaintenanceStore
from src.memory_graph.stats import memory_stats
from src.memory_graph.store import MemoryGraphStore


def setup_memory_graph_routes(
    memory_manager,
    memory_vector=None,
    graph: MemoryGraphStore | None = None,
    maintenance: MemoryMaintenanceStore | None = None,
) -> APIRouter:
    graph = graph or MemoryGraphStore()
    maintenance = maintenance or MemoryMaintenanceStore()
    router = APIRouter(tags=["memory-graph"])

    @router.get("/api/memory/stats")
    def stats():
        return memory_stats(memory_manager, memory_vector)

    @router.get("/api/memory/maintenance/runs")
    def maintenance_runs(owner: str | None = Query(default=None)):
        return {"runs": maintenance.list_runs(owner)}

    @router.post("/api/memory/maintenance/runs")
    async def create_maintenance_run(request: Request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return {"run": maintenance.create_run(payload if isinstance(payload, dict) else {})}

    @router.get("/api/graph/neighborhood")
    def neighborhood(
        owner: str = Query(default="default"),
        node_id: str = Query(...),
        budget: int = Query(default=25),
    ):
        return graph.neighborhood(owner=owner, node_id=node_id, budget=budget)

    return router
