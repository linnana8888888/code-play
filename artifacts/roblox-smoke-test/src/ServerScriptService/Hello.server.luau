-- Runs once per server, prints a line to the Developer Console at startup.
-- Visible at roblox.com/games/<place_id> via the live-ops "Server Log" panel.

local RS = game:GetService("ReplicatedStorage")
local ok, smoke = pcall(require, RS:WaitForChild("SmokeTest"))
if ok and type(smoke) == "table" then
	print(string.format("[smoke-test] %s version=%s created_at=%s", smoke.name, smoke.version, smoke.created_at))
else
	warn("[smoke-test] ReplicatedStorage.SmokeTest missing or not a ModuleScript")
end

game.Players.PlayerAdded:Connect(function(player)
	print(string.format("[smoke-test] player joined: %s (userId=%d)", player.Name, player.UserId))
end)
