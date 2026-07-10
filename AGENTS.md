# Agent Guidance

When working on Odysseus plugins, read `docs/agents/plugin-authoring.md` before editing manifests, plugin runtime code, plugin Settings UI, or plugin tests.

Key reminders:

- Plugins are rule-validated, not manually approved or rejected.
- Invalid plugins must not expose panels or agent tools.
- User opt-in and global enablement are separate gates.
- Keep plugin routes under `/api/plugins/{plugin_id}`.
- Keep plugin panels sandboxed and loaded from `/plugins/{plugin_id}/static/...`.
- Use `examples/plugins/demo_plugin` as the baseline working plugin.
