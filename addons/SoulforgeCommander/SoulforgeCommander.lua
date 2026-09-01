local ConsolePort = ConsolePort

if not ConsolePort
  or type(ConsolePort.GetData) ~= "function"
  or type(ConsolePort.AddPlugin) ~= "function"
  or type(ConsolePort.GetCustomBindingsForRings) ~= "function"
  or type(ConsolePort.RunOOC) ~= "function"
  or not ConsolePortUtilityToggle then
  DEFAULT_CHAT_FRAME:AddMessage("|cffd5a84bSoulforge:|r ConsolePortLK 1.5.0-rc2 is required. Install the complete Soulforge client addon pack.")
  return
end

local cpData = ConsolePort:GetData()
local PACK_VERSION = "2.0.0"
local MANAGED_RING = "soulforge.commands.v1"
local PAGE_SIZE = 8
local companions, pendingRoster = {}, nil
local assembleQueue, assembleElapsed = {}, 0
local syncDelay, currentPage, configPanel = nil, 1, nil

local actions = {
  { id = "Follow", label = "Follow", command = "follow", texture = "Interface\\Icons\\Ability_Hunter_BeastCall" },
  { id = "Stay", label = "Stay", command = "stay", texture = "Interface\\Icons\\Spell_Nature_TimeStop" },
  { id = "Attack", label = "Attack", command = "attack", texture = "Interface\\Icons\\Ability_Warrior_Charge" },
  { id = "TankPull", label = "Tank Pull", command = "tankpull", texture = "Interface\\Icons\\Ability_Warrior_Challange" },
  { id = "Flee", label = "Flee", command = "flee", texture = "Interface\\Icons\\Ability_Rogue_Sprint" },
  { id = "Reset", label = "Reset", command = "reset", texture = "Interface\\Icons\\Spell_Holy_Restoration" },
  { id = "Rebuff", label = "Rebuff", command = "rebuff", texture = "Interface\\Icons\\Spell_Holy_GreaterBlessingofKings" },
  { id = "Companions", label = "Companions", command = "companions", texture = "Interface\\Icons\\INV_Misc_GroupLooking" },
}

local staticScopes = {
  { key = "all", label = "Everyone", prefix = "" },
  { key = "tank", label = "Tank", prefix = "@tank " },
  { key = "healers", label = "Healers", prefix = "@heal " },
  { key = "damage", label = "Damage", prefix = "@dps " },
}

local function database()
  SoulforgeCommanderDB = SoulforgeCommanderDB or {}
  SoulforgeCommanderDB.scopeKey = SoulforgeCommanderDB.scopeKey or "all"
  return SoulforgeCommanderDB
end

local function saveCompanions()
  database().companions = companions
end

local function activeCompanionNames()
  local names = {}
  for _, companion in ipairs(companions) do
    if companion.enabled ~= false then table.insert(names, companion.name) end
  end
  return names
end

local function scopeList()
  local scopes = {}
  for _, scope in ipairs(staticScopes) do table.insert(scopes, scope) end
  for _, companion in ipairs(companions) do
    table.insert(scopes, {
      key = "name:" .. string.lower(companion.name),
      label = companion.name,
      target = companion.name,
    })
  end
  return scopes
end

local function currentScope()
  local key = database().scopeKey
  for _, scope in ipairs(scopeList()) do
    if scope.key == key then return scope end
  end
  database().scopeKey = "all"
  return staticScopes[1]
end

local function channel()
  if GetNumRaidMembers() > 0 then return "RAID" end
  return "PARTY"
end

local function issue(command)
  if command == "companions" then
    configPanel:Show()
    return
  end
  if command == "assemble" then
    local names = activeCompanionNames()
    if #names == 0 then
      DEFAULT_CHAT_FRAME:AddMessage("|cffd5a84bSoulforge:|r No companions are enabled. Open the Companions panel and sync the active world.")
      return
    end
    assembleQueue = {}
    for _, name in ipairs(names) do table.insert(assembleQueue, name) end
    assembleElapsed = 1
    DEFAULT_CHAT_FRAME:AddMessage("|cffd5a84bSoulforge:|r Assembling your enabled companions...")
    return
  end
  local scope = currentScope()
  if command == "tankpull" then
    if scope.target then
      SendChatMessage("pull", "WHISPER", nil, scope.target)
      return
    end
    if GetNumPartyMembers() == 0 and GetNumRaidMembers() == 0 then
      DEFAULT_CHAT_FRAME:AddMessage("|cffd5a84bSoulforge:|r Join a party or raid first.")
      return
    end
    SendChatMessage("@tank pull", channel())
    return
  end
  if scope.target then
    SendChatMessage(command, "WHISPER", nil, scope.target)
    return
  end
  if GetNumPartyMembers() == 0 and GetNumRaidMembers() == 0 then
    DEFAULT_CHAT_FRAME:AddMessage("|cffd5a84bSoulforge:|r Join a party or raid first.")
    return
  end
  SendChatMessage((scope.prefix or "") .. command, channel())
end

local function updateAssembly(elapsed)
  if #assembleQueue == 0 then return end
  assembleElapsed = assembleElapsed + elapsed
  if assembleElapsed < 0.8 then return end
  assembleElapsed = 0
  SendChatMessage(".playerbots bot add " .. table.remove(assembleQueue, 1), "SAY")
end

local function requestRoster()
  pendingRoster = nil
  if configPanel then configPanel.status:SetText("Syncing with the active world...") end
  SendChatMessage(".soulforge roster", "SAY")
end

local function applyServerRoster()
  local previous = {}
  for _, companion in ipairs(companions) do previous[string.lower(companion.name)] = companion end
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
  local count = #(pendingRoster or {})
  companions, pendingRoster = merged, nil
  saveCompanions()
  currentScope()
  if configPanel then
    configPanel.status:SetText("Synced " .. count .. " companions from this world.")
    configPanel:Refresh()
  end
end

local function createButton(name, parent, width, height)
  local atlas = cpData and cpData.Atlas
  if atlas and type(atlas.GetFutureButton) == "function" then
    return atlas.GetFutureButton(name, parent, nil, nil, width, height)
  end
  local button = CreateFrame("Button", name, parent, "UIPanelButtonTemplate")
  button:SetWidth(width)
  button:SetHeight(height)
  return button
end

local function setButtonEnabled(button, enabled)
  if cpData and cpData.CPAPI and type(cpData.CPAPI.SetEnabled) == "function" then
    cpData.CPAPI.SetEnabled(button, enabled)
  elseif enabled then
    button:Enable()
  else
    button:Disable()
  end
end

configPanel = CreateFrame("Frame", "SoulforgeCommanderCompanionPanel", UIParent)
configPanel:SetWidth(560)
configPanel:SetHeight(560)
configPanel:SetPoint("CENTER")
configPanel:SetFrameStrata("DIALOG")
configPanel:SetToplevel(true)
configPanel:SetMovable(true)
configPanel:SetClampedToScreen(true)
configPanel:EnableMouse(true)
configPanel:RegisterForDrag("LeftButton")
configPanel:SetScript("OnDragStart", function(self) self:StartMoving() end)
configPanel:SetScript("OnDragStop", function(self) self:StopMovingOrSizing() end)
configPanel:SetBackdrop({
  bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
  edgeFile = "Interface\\AddOns\\ConsolePort\\Textures\\Window\\EdgefileBig.blp",
  edgeSize = 24,
  insets = { left = 8, right = 8, top = 8, bottom = 8 },
})
configPanel:SetBackdropColor(0.02, 0.04, 0.06, 0.98)

configPanel.title = configPanel:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
configPanel.title:SetPoint("TOPLEFT", 24, -22)
configPanel.title:SetText("Soulforge Companions")

configPanel.version = configPanel:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
configPanel.version:SetPoint("TOPRIGHT", -46, -27)
configPanel.version:SetText("ConsolePort integration " .. PACK_VERSION)

configPanel.close = CreateFrame("Button", "SoulforgeCommanderPanelClose", configPanel, "UIPanelCloseButton")
configPanel.close:SetPoint("TOPRIGHT", -6, -6)

configPanel.help = configPanel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
configPanel.help:SetPoint("TOPLEFT", 24, -52)
configPanel.help:SetPoint("TOPRIGHT", -24, -52)
configPanel.help:SetJustifyH("LEFT")
configPanel.help:SetText("Choose who Assemble invites and who receives ring commands. ConsolePort controls every button in this panel.")

configPanel.sync = createButton("SoulforgeCommanderPanelSync", configPanel, 112, 30)
configPanel.sync:SetPoint("TOPLEFT", 24, -88)
configPanel.sync:SetText("Sync world")
configPanel.sync:SetScript("OnClick", requestRoster)

configPanel.assemble = createButton("SoulforgeCommanderPanelAssemble", configPanel, 138, 30)
configPanel.assemble:SetPoint("LEFT", configPanel.sync, "RIGHT", 10, 0)
configPanel.assemble:SetText("Assemble enabled")
configPanel.assemble:SetScript("OnClick", function() issue("assemble") end)

configPanel.target = createButton("SoulforgeCommanderPanelTarget", configPanel, 154, 30)
configPanel.target:SetPoint("LEFT", configPanel.assemble, "RIGHT", 10, 0)
configPanel.target:SetScript("OnClick", function()
  local scopes, selected = scopeList(), 1
  for index, scope in ipairs(scopes) do
    if scope.key == database().scopeKey then selected = index; break end
  end
  selected = selected + 1
  if selected > #scopes then selected = 1 end
  database().scopeKey = scopes[selected].key
  configPanel:Refresh()
end)

configPanel.status = configPanel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
configPanel.status:SetPoint("TOPLEFT", 26, -126)
configPanel.status:SetPoint("TOPRIGHT", -26, -126)
configPanel.status:SetJustifyH("LEFT")
configPanel.status:SetText("Waiting for the active world's roster.")

configPanel.headers = configPanel:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
configPanel.headers:SetPoint("TOPLEFT", 30, -150)
configPanel.headers:SetText("USE     NAME                         ROLE          COMMAND TARGET")

configPanel.rows = {}
for index = 1, PAGE_SIZE do
  local row = CreateFrame("Frame", "SoulforgeCommanderCompanionRow" .. index, configPanel)
  row:SetWidth(510)
  row:SetHeight(34)
  row:SetPoint("TOPLEFT", 24, -168 - ((index - 1) * 36))
  row.check = CreateFrame("CheckButton", row:GetName() .. "Enable", row, "UICheckButtonTemplate")
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
  row.role:SetPoint("LEFT", 224, 0)
  row.role:SetWidth(65)
  row.role:SetJustifyH("LEFT")
  row.target = createButton(row:GetName() .. "Target", row, 92, 24)
  row.target:SetPoint("LEFT", 294, 0)
  row.target:SetText("Target")
  row.target:SetScript("OnClick", function()
    if row.companion then
      database().scopeKey = "name:" .. string.lower(row.companion.name)
      configPanel:Refresh()
    end
  end)
  row.remove = createButton(row:GetName() .. "Remove", row, 74, 24)
  row.remove:SetPoint("RIGHT", 0, 0)
  row.remove:SetText("Remove")
  row.remove:SetScript("OnClick", function()
    if not row.companion or row.companion.source ~= "custom" then return end
    for companionIndex, companion in ipairs(companions) do
      if companion == row.companion then table.remove(companions, companionIndex); break end
    end
    saveCompanions()
    currentScope()
    configPanel:Refresh()
  end)
  configPanel.rows[index] = row
end

configPanel.previous = createButton("SoulforgeCommanderPanelPrevious", configPanel, 86, 26)
configPanel.previous:SetPoint("BOTTOMLEFT", 24, 78)
configPanel.previous:SetText("Previous")
configPanel.previous:SetScript("OnClick", function()
  currentPage = math.max(1, currentPage - 1)
  configPanel:Refresh()
end)

configPanel.page = configPanel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
configPanel.page:SetPoint("LEFT", configPanel.previous, "RIGHT", 12, 0)
configPanel.page:SetWidth(80)
configPanel.page:SetJustifyH("CENTER")

configPanel.next = createButton("SoulforgeCommanderPanelNext", configPanel, 86, 26)
configPanel.next:SetPoint("LEFT", configPanel.page, "RIGHT", 12, 0)
configPanel.next:SetText("Next")
configPanel.next:SetScript("OnClick", function()
  local pages = math.max(1, math.ceil(#companions / PAGE_SIZE))
  currentPage = math.min(pages, currentPage + 1)
  configPanel:Refresh()
end)

configPanel.addLabel = configPanel:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
configPanel.addLabel:SetPoint("BOTTOMLEFT", 26, 50)
configPanel.addLabel:SetText("Add a local character name")

configPanel.addName = CreateFrame("EditBox", "SoulforgeCommanderPanelAddName", configPanel, "InputBoxTemplate")
configPanel.addName:SetWidth(250)
configPanel.addName:SetHeight(28)
configPanel.addName:SetPoint("BOTTOMLEFT", 26, 18)
configPanel.addName:SetAutoFocus(false)
configPanel.addName:SetMaxLetters(12)

configPanel.add = createButton("SoulforgeCommanderPanelAdd", configPanel, 92, 26)
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
  currentPage = math.ceil(#companions / PAGE_SIZE)
  configPanel:Refresh()
end)
configPanel.addName:SetScript("OnEnterPressed", function(self)
  configPanel.add:Click()
  self:ClearFocus()
end)

function configPanel:Refresh()
  local pages = math.max(1, math.ceil(#companions / PAGE_SIZE))
  currentPage = math.min(math.max(1, currentPage), pages)
  local offset = (currentPage - 1) * PAGE_SIZE
  local selectedKey = database().scopeKey
  for index, row in ipairs(self.rows) do
    local companion = companions[offset + index]
    row.companion = companion
    if companion then
      row.name:SetText(companion.name)
      row.role:SetText(companion.role or "dps")
      row.check:SetChecked(companion.enabled ~= false)
      row.target:SetText(selectedKey == "name:" .. string.lower(companion.name) and "Selected" or "Target")
      if companion.source == "custom" then row.remove:Show() else row.remove:Hide() end
      row:Show()
    else
      row:Hide()
    end
  end
  self.target:SetText("Target: " .. currentScope().label)
  self.page:SetText(currentPage .. " / " .. pages)
  setButtonEnabled(self.previous, currentPage > 1)
  setButtonEnabled(self.next, currentPage < pages)
end

configPanel:SetScript("OnShow", function(self)
  self:Refresh()
  requestRoster()
  if type(ConsolePort.SetCurrentNode) == "function" then ConsolePort:SetCurrentNode(self.sync) end
end)
configPanel:Hide()

local originalRingBindings = ConsolePort.GetCustomBindingsForRings
function ConsolePort:GetCustomBindingsForRings()
  local bindings = originalRingBindings(self) or {}
  local seen = {}
  for _, binding in ipairs(bindings) do seen[binding.binding] = true end
  for _, action in ipairs(actions) do
    local binding = "CLICK SoulforgeCommanderAction" .. action.id .. ":LeftButton"
    if not seen[binding] then
      table.insert(bindings, { name = "Soulforge: " .. action.label, binding = binding, texture = action.texture })
    end
  end
  return bindings
end

for _, actionDefinition in ipairs(actions) do
  local action = actionDefinition
  local button = CreateFrame("Button", "SoulforgeCommanderAction" .. action.id, UIParent, "SecureActionButtonTemplate")
  button:SetWidth(1)
  button:SetHeight(1)
  button:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", -20, -20)
  button:SetAlpha(0)
  button:RegisterForClicks("AnyUp")
  button:SetScript("OnClick", function() issue(action.command) end)
  button:Show()
end

local function managedRingData()
  local data = {}
  for index, action in ipairs(actions) do
    data[index] = {
      action = "custom",
      value = "CLICK SoulforgeCommanderAction" .. action.id .. ":LeftButton",
      autoassigned = false,
    }
  end
  return data
end

local function ensureManagedRing()
  ConsolePortUtility = ConsolePortUtility or {}
  local ring, ringID
  for id, candidate in pairs(ConsolePortUtility) do
    if candidate.SoulforgeManaged == MANAGED_RING
      or (candidate.Name == "Soulforge Commander" and not candidate.SoulforgeManaged) then
      ring, ringID = candidate, id
      break
    end
  end
  if not ring then
    ringID = #ConsolePortUtility + 1
    ring = {}
    ConsolePortUtility[ringID] = ring
  end
  ring.Name = "Soulforge Commander"
  ring.Icon = "Interface\\Icons\\INV_Misc_GroupLooking"
  ring.Autoassign = false
  ring.SoulforgeManaged = MANAGED_RING
  ring.Data = managedRingData()
  database().ringID = ringID
  ConsolePort:RunOOC(function()
    if ConsolePortUtilityToggle and type(ConsolePortUtilityToggle.Refresh) == "function" then
      ConsolePortUtilityToggle:Refresh()
    end
  end)
end

ConsolePort:AddPlugin("SoulforgeCommander", function(self)
  self:AddFrame(configPanel)
  self:UpdateFrames()
end)

local eventFrame = CreateFrame("Frame", "SoulforgeCommanderEvents")
eventFrame:RegisterEvent("PLAYER_LOGIN")
eventFrame:RegisterEvent("PARTY_MEMBERS_CHANGED")
eventFrame:RegisterEvent("RAID_ROSTER_UPDATE")
eventFrame:RegisterEvent("CHAT_MSG_SYSTEM")
eventFrame:SetScript("OnEvent", function(_, event, message)
  if event == "PLAYER_LOGIN" then
    local saved = database()
    companions = saved.companions or {}
    ensureManagedRing()
    syncDelay = 3
  elseif event == "CHAT_MSG_SYSTEM" and message then
    if message == "SOULFORGE_ROSTER:BEGIN" then
      pendingRoster = {}
    elseif message == "SOULFORGE_ROSTER:END" and pendingRoster then
      applyServerRoster()
    elseif message == "SOULFORGE_ROSTER:ERROR" then
      pendingRoster = nil
      configPanel.status:SetText("Server sync unavailable; saved companions are unchanged.")
    elseif pendingRoster then
      local name, role = message:match("^SOULFORGE_ROSTER:([^:]+):([^:]+)$")
      if name and role then table.insert(pendingRoster, { name = name, role = role }) end
    end
  end
  if configPanel:IsShown() then configPanel:Refresh() end
end)

eventFrame:SetScript("OnUpdate", function(self, elapsed)
  updateAssembly(elapsed)
  if not syncDelay then return end
  syncDelay = syncDelay - elapsed
  if syncDelay <= 0 then
    syncDelay = nil
    requestRoster()
  end
end)

if ChatFrame_AddMessageEventFilter then
  ChatFrame_AddMessageEventFilter("CHAT_MSG_SYSTEM", function(_, _, message)
    if message and message:find("^SOULFORGE_ROSTER:") then return true end
    return false
  end)
end

SLASH_SOULFORGECOMMANDER1 = "/sfc"
SlashCmdList.SOULFORGECOMMANDER = function(message)
  message = string.lower((message or ""):gsub("^%s+", ""):gsub("%s+$", ""))
  if message == "sync" then
    requestRoster()
  elseif message == "assemble" then
    issue("assemble")
  elseif message == "status" then
    DEFAULT_CHAT_FRAME:AddMessage(
      "|cffd5a84bSoulforge:|r ConsolePort ring " .. tostring(database().ringID or "pending")
      .. ", " .. #companions .. " companions, target " .. currentScope().label .. "."
    )
  else
    configPanel:Show()
  end
end
