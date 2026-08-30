local wheel = CreateFrame("Frame", "SoulforgeCommanderWheel", UIParent)
local scopes = {
  { label = "Everyone", prefix = "" },
  { label = "Tank", prefix = "@tank " },
  { label = "Healers", prefix = "@heal " },
  { label = "Damage", prefix = "@dps " },
}
local actions = {
  { label = "Assemble", command = "assemble" },
  { label = "Follow", command = "follow" },
  { label = "Attack", command = "attack" },
  { label = "Tank pull", command = "tankpull" },
  { label = "Flee", command = "flee" },
  { label = "Reset", command = "reset" },
  { label = "Rebuff", command = "rebuff" },
  { label = "Stay", command = "stay" },
}
local scopeIndex, selectedIndex = 1, nil
local companionNames = SoulforgeCommanderCompanions or {}
local assembleQueue, assembleElapsed = {}, 0

BINDING_HEADER_SOULFORGE_COMMANDER = "Soulforge Commander"
BINDING_NAME_SOULFORGE_TOGGLE = "Hold command wheel"

local function channel()
  if GetNumRaidMembers() > 0 then return "RAID" end
  return "PARTY"
end

local function issue(command)
  if command == "assemble" then
    if #companionNames == 0 then
      DEFAULT_CHAT_FRAME:AddMessage("|cffd5a84bSoulforge:|r No companions are configured. Forge or promote companions, then download the addon again.")
      return
    end
    assembleQueue = {}
    for _, name in ipairs(companionNames) do table.insert(assembleQueue, name) end
    assembleElapsed = 1
    DEFAULT_CHAT_FRAME:AddMessage("|cffd5a84bSoulforge:|r Assembling your forged companions...")
    return
  end
  local scope = scopes[scopeIndex]
  if command == "tankpull" then
    if scope.target then
      command = "pull"
    else
      if GetNumPartyMembers() == 0 and GetNumRaidMembers() == 0 then
        DEFAULT_CHAT_FRAME:AddMessage("|cffd5a84bSoulforge:|r Join a party or raid first.")
        return
      end
      SendChatMessage("@tank pull", channel())
      return
    end
  end
  if scope.target then
    SendChatMessage(command, "WHISPER", nil, scope.target)
    return
  end
  if GetNumPartyMembers() == 0 and GetNumRaidMembers() == 0 then
    DEFAULT_CHAT_FRAME:AddMessage("|cffd5a84bSoulforge:|r Join a party or raid first.")
    return
  end
  SendChatMessage(scope.prefix .. command, channel())
end

local function updateAssembly(elapsed)
  if #assembleQueue == 0 then return end
  assembleElapsed = assembleElapsed + elapsed
  if assembleElapsed < 0.8 then return end
  assembleElapsed = 0
  local name = table.remove(assembleQueue, 1)
  SendChatMessage(".playerbots bot add " .. name, "SAY")
end

local function updateCenter()
  wheel.center:SetText(scopes[scopeIndex].label)
end

local function rebuildScopes()
  while #scopes > 4 do table.remove(scopes) end
  local total = GetNumRaidMembers() > 0 and GetNumRaidMembers() or GetNumPartyMembers()
  local prefix = GetNumRaidMembers() > 0 and "raid" or "party"
  for index = 1, total do
    local name = UnitName(prefix .. index)
    if name and name ~= UnitName("player") then
      table.insert(scopes, { label = name, target = name })
    end
  end
  if scopeIndex > #scopes then scopeIndex = 1 end
  updateCenter()
end

local function setSelected(index)
  if selectedIndex == index then return end
  if selectedIndex then wheel.buttons[selectedIndex]:UnlockHighlight() end
  selectedIndex = index
  if selectedIndex then
    wheel.buttons[selectedIndex]:LockHighlight()
    wheel.selection:SetText(actions[selectedIndex].label)
  else
    wheel.selection:SetText("Move to choose")
  end
end

local function trackMouse()
  local scale = UIParent:GetEffectiveScale()
  local mouseX, mouseY = GetCursorPosition()
  mouseX, mouseY = mouseX / scale, mouseY / scale
  local centerX, centerY = wheel:GetCenter()
  local distanceFromCenter = ((mouseX - centerX) ^ 2 + (mouseY - centerY) ^ 2) ^ 0.5
  if distanceFromCenter < 34 then setSelected(nil); return end
  local nearest, nearestDistance = nil, nil
  for index, button in ipairs(wheel.buttons) do
    local x, y = button:GetCenter()
    local distance = (mouseX - x) ^ 2 + (mouseY - y) ^ 2
    if not nearestDistance or distance < nearestDistance then
      nearest, nearestDistance = index, distance
    end
  end
  setSelected(nearest)
end

local function openWheel()
  rebuildScopes()
  local scale = UIParent:GetEffectiveScale()
  local x, y = GetCursorPosition()
  local radius = 155
  x = math.max(radius * scale, math.min(x, (UIParent:GetWidth() - radius) * scale))
  y = math.max(radius * scale, math.min(y, (UIParent:GetHeight() - radius) * scale))
  wheel:ClearAllPoints()
  wheel:SetPoint("CENTER", UIParent, "BOTTOMLEFT", x / scale, y / scale)
  setSelected(nil)
  wheel:Show()
end

local function closeWheel(execute)
  local action = selectedIndex and actions[selectedIndex]
  wheel:Hide()
  if execute and action then issue(action.command) end
  setSelected(nil)
end

wheel:SetWidth(300)
wheel:SetHeight(300)
wheel:SetFrameStrata("DIALOG")
wheel:EnableMouse(true)
wheel:EnableMouseWheel(true)
wheel:SetBackdrop({ bgFile = "Interface/Tooltips/UI-Tooltip-Background", edgeFile = "Interface/Tooltips/UI-Tooltip-Border", edgeSize = 18, insets = { left = 5, right = 5, top = 5, bottom = 5 } })
wheel:SetBackdropColor(0.025, 0.04, 0.055, 0.92)
wheel:SetScript("OnUpdate", function(_, elapsed)
  if wheel:IsShown() then trackMouse() end
  updateAssembly(elapsed)
end)
wheel:SetScript("OnMouseWheel", function(_, delta)
  scopeIndex = scopeIndex + (delta > 0 and 1 or -1)
  if scopeIndex > #scopes then scopeIndex = 1 end
  if scopeIndex < 1 then scopeIndex = #scopes end
  updateCenter()
end)
wheel:SetScript("OnMouseDown", function(_, button)
  if button == "RightButton" then closeWheel(false) end
end)
wheel.buttons = {}

wheel.center = CreateFrame("Button", nil, wheel, "UIPanelButtonTemplate")
wheel.center:SetWidth(88)
wheel.center:SetHeight(35)
wheel.center:SetPoint("CENTER", 0, 0)
wheel.center:SetScript("OnClick", function()
  scopeIndex = scopeIndex + 1
  if scopeIndex > #scopes then scopeIndex = 1 end
  updateCenter()
end)

wheel.selection = wheel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
wheel.selection:SetPoint("TOP", wheel.center, "BOTTOM", 0, -5)
wheel.selection:SetText("Move to choose")

for index, action in ipairs(actions) do
  local angle = math.rad(90 - ((index - 1) * (360 / #actions)))
  local button = CreateFrame("Button", nil, wheel, "UIPanelButtonTemplate")
  button:SetWidth(82)
  button:SetHeight(30)
  button:SetPoint("CENTER", wheel, "CENTER", math.cos(angle) * 105, math.sin(angle) * 105)
  button:SetText(action.label)
  button:SetScript("OnEnter", function() setSelected(index) end)
  button:SetScript("OnClick", function() closeWheel(false); issue(action.command) end)
  wheel.buttons[index] = button
end

wheel:RegisterEvent("PLAYER_LOGIN")
wheel:RegisterEvent("PARTY_MEMBERS_CHANGED")
wheel:RegisterEvent("RAID_ROSTER_UPDATE")
wheel:SetScript("OnEvent", function(_, event)
  if event == "PLAYER_LOGIN" then
    SoulforgeCommanderDB = SoulforgeCommanderDB or {}
    scopeIndex = tonumber(SoulforgeCommanderDB.scopeIndex) or 1
  end
  rebuildScopes()
end)
wheel:Hide()

function SoulforgeCommander_Binding(state)
  if state == "down" then
    openWheel()
  elseif state == "up" then
    closeWheel(true)
  elseif wheel:IsShown() then
    closeWheel(false)
  else
    openWheel()
  end
  SoulforgeCommanderDB = SoulforgeCommanderDB or {}
  SoulforgeCommanderDB.scopeIndex = scopeIndex
end

function SoulforgeCommander_Toggle()
  if wheel:IsShown() then closeWheel(false) else openWheel() end
end

SLASH_SOULFORGECOMMANDER1 = "/sfc"
SlashCmdList.SOULFORGECOMMANDER = SoulforgeCommander_Toggle
