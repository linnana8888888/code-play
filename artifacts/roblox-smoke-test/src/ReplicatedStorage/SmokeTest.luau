-- Smoke test ModuleScript for the code-play publisher's Roblox target.
-- This file exists to prove the publisher plumbing works end-to-end:
--   Rojo build → .rbxlx → Open Cloud POST → live listing.
-- If you're seeing this in a shipped place, the chain is working.

return {
	name = "roblox-smoke-test",
	purpose = "code-play publisher plumbing smoke test",
	version = "v1",
	created_at = "2026-04-19",
	upstream = "https://github.com/linnana8888888/code-play/tree/main/artifacts/roblox-smoke-test",
}
