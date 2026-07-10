"""Example Odysseus plugin entrypoint."""

from fastapi import APIRouter


def register_plugin(context):
    router = APIRouter()

    @router.get("/health")
    def health():
        return {
            "ok": True,
            "plugin_id": context.manifest.id,
            "version": context.manifest.version,
        }

    def echo(args, ctx):
        return {
            "plugin": context.manifest.id,
            "owner": (ctx or {}).get("owner"),
            "echo": str((args or {}).get("text", "")),
        }

    context.register_router(router)
    context.register_tool("echo", echo)
