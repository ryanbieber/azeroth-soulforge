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
local assembleQueue, assembleElapsed = {}, 0
local companions, pendingRoster = {}, nil
local configPanel, syncDelay

BINDING_HEADER_SOULFORGE_COMMANDER = "Soulforge Commander"
BINDING_NAME_SOULFORGE_TOGGLE = "Hold command wheel"

local function channel()
  if GetNumRaidMembers() > 0 then return "RAID" end
  return "PARTY"
end

local function saveCompanions()
  SoulforgeCommanderDB = SoulforgeCommanderDB or {}
  SoulforgeCommanderDB.companions = companions
end

local function activeCompanionNames()
  local names = {}
  for _, companion in ipairs(companions) do
    if companion.enabled ~= false then table.insert(names, companion.name) end
  end
  return names
end

local function requestRoster()
  pendingRoster = nil
  if configPanel then configPanel.status:SetText("Syncing with the active world...") end
  SendChatMessage(".soulforge roster", "SAY")
end

local function applyServerRoster()
  local serverCount = #(pendingRoster or {})
  local previous = {}
  for _, companion in ipairs(companions) do
    previous[string.lower(companion.name)] = companion
  end
  local merged = {}
  for _, serverCompanion in ipairs(pendingRoster or {}) do
    local old = previous[string.lower(serverCompanion.name)]
    table.insert(merged, {
      name = serverCompanion.name,
      role = serverCompanion.role,
      enabled = not old or old.enabled ~= false,
      source = "server",
    })
  end
  for _, companion in ipairs(companions) do
    if companion.source == "custom" then table.insert(merged, companion) end
  end
  companions, pendingRoster = merged, nil
  saveCompanions()
  if configPanel then
    configPanel.status:SetText("Synced " .. serverCount .. " companions from this world.")
    configPanel:Refresh()
  end
end

local function issue(command)
  if command == "assemble" then
    local companionNames = activeCompanionNames()
    if #companionNames == 0 then
      DEFAULT_CHAT_FRAME:AddMessage("|cffd5a84bSoulforge:|r No companions are enabled. Open Companion Setup and sync or add one.")
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

configPanel = CreateFrame("Frame", "SoulforgeCommanderConfig", UIParent)
configPanel:SetWidth(440)
configPanel:SetHeight(500)
configPanel:SetPoint("CENTER")
configPanel:SetFrameStrata("DIALOG")
configPanel:SetToplevel(true)
configPanel:SetMovable(true)
configPanel:EnableMouse(true)
configPanel:RegisterForDrag("LeftButton")
configPanel:SetScript("OnDragStart", function(self) self:StartMoving() end)
configPanel:SetScript("OnDragStop", function(self) self:StopMovingOrSizing() end)
configPanel:SetBackdrop({ bgFile = "Interface/Tooltips/UI-Tooltip-Background", edgeFile = "Interface/Tooltips/UI-Tooltip-Border", edgeSize = 18, insets = { left = 5, right = 5, top = 5, bottom = 5 } })
configPanel:SetBackdropColor(0.025, 0.04, 0.055, 0.97)

configPanel.title = configPanel:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
configPanel.title:SetPoint("TOPLEFT", 20, -18)
configPanel.title:SetText("Soulforge Companions")

configPanel.close = CreateFrame("Button", nil, configPanel, "UIPanelCloseButton")
configPanel.close:SetPoint("TOPRIGHT", -5, -5)

configPanel.help = configPanel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
configPanel.help:SetPoint("TOPLEFT", 20, -48)
configPanel.help:SetPoint("TOPRIGHT", -20, -48)
configPanel.help:SetJustifyH("LEFT")
configPanel.help:SetText("The active world's companions sync automatically. Uncheck anyone you do not want Assemble to invite, or add a local character name.")

configPanel.sync = CreateFrame("Button", nil, configPanel, "UIPanelButtonTemplate")
configPanel.sync:SetWidth(150)
configPanel.sync:SetHeight(25)
configPanel.sync:SetPoint("TOPLEFT", 20, -88)
configPanel.sync:SetText("Sync from server")
configPanel.sync:SetScript("OnClick", requestRoster)

configPanel.status = configPanel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
configPanel.status:SetPoint("LEFT", configPanel.sync, "RIGHT", 12, 0)
configPanel.status:SetPoint("RIGHT", configPanel, "RIGHT", -20, 0)
configPanel.status:SetJustifyH("LEFT")
configPanel.status:SetText("Waiting for server sync.")

configPanel.headers = configPanel:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
configPanel.headers:SetPoint("TOPLEFT", 24, -126)
configPanel.headers:SetText("USE        NAME                              ROLE")

configPanel.rows = {}
for index = 1, 10 do
  local row = CreateFrame("Frame", nil, configPanel)
  row:SetWidth(395)
  row:SetHeight(28)
  row:SetPoint("TOPLEFT", 20, -138 - ((index - 1) * 29))
  row.check = CreateFrame("CheckButton", nil, row, "UICheckButtonTemplate")
  row.check:SetPoint("LEFT", 0, 0)
  row.check:SetScript("OnClick", function(self)
    if row.companion then
      row.companion.enabled = self:GetChecked() and true or false
      saveCompanions()
    end
  end)
  row.name = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.name:SetPoint("LEFT", 42, 0)
  row.name:SetWidth(180)
  row.name:SetJustifyH("LEFT")
  row.role = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  row.role:SetPoint("LEFT", 225, 0)
  row.role:SetWidth(90)
  row.role:SetJustifyH("LEFT")
  row.remove = CreateFrame("Button", nil, row, "UIPanelButtonTemplate")
  row.remove:SetWidth(65)
  row.remove:SetHeight(22)
  row.remove:SetPoint("RIGHT", 0, 0)
  row.remove:SetText("Remove")
  row.remove:SetScript("OnClick", function()
    if not row.companion or row.companion.source ~= "custom" then return end
    for companionIndex, companion in ipairs(companions) do
      if companion == row.companion then table.remove(companions, companionIndex); break end
    end
    saveCompanions()
    configPanel:Refresh()
  end)
  configPanel.rows[index] = row
end

configPanel.addLabel = configPanel:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
configPanel.addLabel:SetPoint("BOTTOMLEFT", 22, 58)
configPanel.addLabel:SetText("Add a local companion")

configPanel.addName = CreateFrame("EditBox", nil, configPanel, "InputBoxTemplate")
configPanel.addName:SetWidth(230)
configPanel.addName:SetHeight(28)
configPanel.addName:SetPoint("BOTTOMLEFT", 22, 24)
configPanel.addName:SetAutoFocus(false)
configPanel.addName:SetMaxLetters(12)

configPanel.add = CreateFrame("Button", nil, configPanel, "UIPanelButtonTemplate")
configPanel.add:SetWidth(100)
configPanel.add:SetHeight(25)
configPanel.add:SetPoint("LEFT", configPanel.addName, "RIGHT", 12, 0)
configPanel.add:SetText("Add")
configPanel.add:SetScript("OnClick", function()
  local name = configPanel.addName:GetText():gsub("%s+", "")
  if #name < 2 or #name > 12 or not name:match("^%a+$") then
    configPanel.status:SetText("Enter a 2-12 letter WoW character name.")
    return
  end
  for _, companion in ipairs(companions) do
    if string.lower(companion.name) == string.lower(name) then
      companion.enabled = true
      saveCompanions()
      configPanel.addName:SetText("")
      configPanel:Refresh()
      return
    end
  end
  table.insert(companions, { name = name, role = "local", enabled = true, source = "custom" })
  saveCompanions()
  configPanel.addName:SetText("")
  configPanel:Refresh()
end)
configPanel.addName:SetScript("OnEnterPressed", function(self) configPanel.add:Click(); self:ClearFocus() end)

function configPanel:Refresh()
  for index, row in ipairs(self.rows) do
    local companion = companions[index]
    row.companion = companion
    if companion then
      row.name:SetText(companion.name)
      row.role:SetText(companion.role or "dps")
      row.check:SetChecked(companion.enabled ~= false)
      if companion.source == "custom" then row.remove:Show() else row.remove:Hide() end
      row:Show()
    else
      row:Hide()
    end
  end
  if #companions > #self.rows then
    self.status:SetText("Showing the first " .. #self.rows .. " companions.")
  end
end

configPanel:SetScript("OnShow", function(self) self:Refresh(); requestRoster() end)
configPanel:Hide()

wheel.configure = CreateFrame("Button", nil, wheel, "UIPanelButtonTemplate")
wheel.configure:SetWidth(96)
wheel.configure:SetHeight(22)
wheel.configure:SetPoint("CENTER", wheel, "CENTER", 0, 57)
wheel.configure:SetText("Companions")
wheel.configure:SetScript("OnClick", function() closeWheel(false); configPanel:Show() end)

wheel:RegisterEvent("PLAYER_LOGIN")
wheel:RegisterEvent("PARTY_MEMBERS_CHANGED")
wheel:RegisterEvent("RAID_ROSTER_UPDATE")
wheel:RegisterEvent("CHAT_MSG_SYSTEM")
wheel:SetScript("OnEvent", function(_, event, message)
  if event == "PLAYER_LOGIN" then
    SoulforgeCommanderDB = SoulforgeCommanderDB or {}
    scopeIndex = tonumber(SoulforgeCommanderDB.scopeIndex) or 1
    companions = SoulforgeCommanderDB.companions or {}
    syncDelay = 3
  elseif event == "CHAT_MSG_SYSTEM" and message then
    if message == "SOULFORGE_ROSTER:BEGIN" then
      pendingRoster = {}
    elseif message == "SOULFORGE_ROSTER:END" and pendingRoster then
      applyServerRoster()
    elseif message == "SOULFORGE_ROSTER:ERROR" then
      pendingRoster = nil
      if configPanel then configPanel.status:SetText("Server sync unavailable; saved companions are unchanged.") end
    elseif pendingRoster then
      local name, role = message:match("^SOULFORGE_ROSTER:([^:]+):([^:]+)$")
      if name and role then table.insert(pendingRoster, { name = name, role = role }) end
    end
  end
  rebuildScopes()
end)
wheel:Hide()

local syncFrame = CreateFrame("Frame")
syncFrame:SetScript("OnUpdate", function(self, elapsed)
  if not syncDelay then return end
  syncDelay = syncDelay - elapsed
  if syncDelay <= 0 then
    syncDelay = nil
    requestRoster()
    self:Hide()
  end
end)

if ChatFrame_AddMessageEventFilter then
  ChatFrame_AddMessageEventFilter("CHAT_MSG_SYSTEM", function(_, _, message)
    if message and message:find("^SOULFORGE_ROSTER:") then return true end
    return false
  end)
end

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
SlashCmdList.SOULFORGECOMMANDER = function(message)
  message = string.lower((message or ""):gsub("^%s+", ""):gsub("%s+$", ""))
  if message == "config" or message == "companions" then
    configPanel:Show()
  elseif message == "sync" then
    requestRoster()
  else
    SoulforgeCommander_Toggle()
  end
end
