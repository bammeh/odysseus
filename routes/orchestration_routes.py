from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.auth_helpers import effective_user
from src.orchestration.store import OrchestrationError, OrchestrationStore


async def _json(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _owner(request: Request) -> str:
    return effective_user(request) or "default"


def _handle_error(exc: OrchestrationError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def setup_orchestration_routes(store: OrchestrationStore | None = None) -> APIRouter:
    store = store or OrchestrationStore()
    router = APIRouter(prefix="/api/orchestration", tags=["orchestration"])

    @router.get("/profile-templates")
    def profile_templates():
        return {"templates": store.templates()}

    @router.get("/profiles")
    def list_profiles(request: Request):
        return {"profiles": store.list_profiles(_owner(request))}

    @router.post("/profiles")
    async def create_profile(request: Request):
        try:
            return {"profile": store.create_profile(_owner(request), await _json(request))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.patch("/profiles/{profile_id}")
    async def update_profile(profile_id: str, request: Request):
        try:
            return {"profile": store.update_profile(_owner(request), profile_id, await _json(request))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.post("/profiles/{profile_id}/duplicate")
    async def duplicate_profile(profile_id: str, request: Request):
        payload = await _json(request)
        try:
            return {"profile": store.duplicate_profile(_owner(request), profile_id, payload.get("display_name"))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.delete("/profiles/{profile_id}")
    def delete_profile(profile_id: str, request: Request):
        try:
            store.delete_profile(_owner(request), profile_id)
        except OrchestrationError as exc:
            raise _handle_error(exc)
        return {"ok": True}

    @router.get("/teams")
    def list_teams(request: Request):
        return {"teams": store.list_teams(_owner(request))}

    @router.post("/teams")
    async def create_team(request: Request):
        try:
            return {"team": store.create_team(_owner(request), await _json(request))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.patch("/teams/{team_id}")
    async def update_team(team_id: str, request: Request):
        try:
            return {"team": store.update_team(_owner(request), team_id, await _json(request))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.post("/teams/{team_id}/duplicate")
    async def duplicate_team(team_id: str, request: Request):
        payload = await _json(request)
        try:
            return {"team": store.duplicate_team(_owner(request), team_id, payload.get("name"))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.delete("/teams/{team_id}")
    def delete_team(team_id: str, request: Request):
        try:
            store.delete_team(_owner(request), team_id)
        except OrchestrationError as exc:
            raise _handle_error(exc)
        return {"ok": True}

    @router.get("/runs")
    def list_runs(request: Request):
        return {"runs": store.list_runs(_owner(request))}

    @router.post("/runs")
    async def create_run(request: Request):
        try:
            return {"run": store.create_run(_owner(request), await _json(request))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.get("/runs/{run_id}/snapshot")
    def run_snapshot(run_id: str, request: Request):
        try:
            return {"snapshot": store.snapshot(_owner(request), run_id)}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.post("/runs/{run_id}/tasks/{task_id}/start")
    async def start_task(run_id: str, task_id: str, request: Request):
        try:
            return {"task": store.start_task(_owner(request), run_id, task_id, await _json(request))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.post("/runs/{run_id}/tasks/{task_id}/attach-session")
    async def attach_task_session(run_id: str, task_id: str, request: Request):
        payload = await _json(request)
        try:
            return {"task": store.attach_task_session(_owner(request), run_id, task_id, payload.get("session_id", ""))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.post("/runs/{run_id}/tasks/{task_id}/transition")
    async def transition_task(run_id: str, task_id: str, request: Request):
        try:
            return {"task": store.transition_task(_owner(request), run_id, task_id, await _json(request))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.get("/runs/{run_id}/tasks/{task_id}/context")
    def task_context(run_id: str, task_id: str, request: Request):
        try:
            return store.task_context(_owner(request), run_id, task_id)
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.post("/runs/{run_id}/tasks/{task_id}/reflector-review")
    async def reflector_review(run_id: str, task_id: str, request: Request):
        try:
            return {"review": store.reflector_review(_owner(request), run_id, task_id, await _json(request))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.post("/handoffs")
    async def create_handoff(request: Request):
        try:
            return {"handoff": store.create_handoff(_owner(request), await _json(request))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.post("/handoffs/{handoff_id}/review")
    async def review_handoff(handoff_id: str, request: Request):
        try:
            return store.review_handoff(_owner(request), handoff_id, await _json(request))
        except OrchestrationError as exc:
            raise _handle_error(exc)

    @router.post("/quality-gates")
    async def evaluate_quality_gate(request: Request):
        try:
            return {"result": store.evaluate_quality_gate(_owner(request), await _json(request))}
        except OrchestrationError as exc:
            raise _handle_error(exc)

    return router
