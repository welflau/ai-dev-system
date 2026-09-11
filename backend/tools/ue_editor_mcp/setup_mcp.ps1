# ============================================================================
#  UEEditorMCP - One-Click Python Setup (PowerShell)
#  Automatically finds UE engine's built-in Python, creates a venv,
#  and installs the MCP package. No external Python installation required.
# ============================================================================

param(
    [string]$EngineRoot = ""
)

$ErrorActionPreference = "Stop"
$PluginDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonDir  = Join-Path $PluginDir "Python"
$VenvDir    = Join-Path $PythonDir ".venv"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PluginDir)  # Up from Plugins/UEEditorMCP

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " UEEditorMCP - Python Environment Setup"  -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# --- Step 1: Find UE Engine Python ---
Write-Host "[1/4] Searching for Unreal Engine Python..." -ForegroundColor Yellow

$UEPython = $null

# --- Priority 1: User-provided engine root ---
if ($EngineRoot -ne "") {
    $candidate = Join-Path $EngineRoot "Engine\Binaries\ThirdParty\Python3\Win64\python.exe"
    if (Test-Path $candidate) {
        $UEPython = $candidate
        Write-Host "  [user param] $UEPython" -ForegroundColor DarkGray
    }
}

# --- Priority 2: Read .uproject EngineAssociation → Windows Registry ---
if (-not $UEPython) {
    $uprojectFiles = Get-ChildItem -Path $ProjectRoot -Filter "*.uproject" -ErrorAction SilentlyContinue
    foreach ($upf in $uprojectFiles) {
        try {
            $upContent = Get-Content $upf.FullName -Raw | ConvertFrom-Json
            $engineVer = $upContent.EngineAssociation
            if ($engineVer) {
                Write-Host "  Found EngineAssociation: $engineVer" -ForegroundColor DarkGray

                # Try HKLM installed engine (e.g. "5.7" → HKLM\SOFTWARE\EpicGames\Unreal Engine\5.7)
                $regPath = "HKLM:\SOFTWARE\EpicGames\Unreal Engine\$engineVer"
                try {
                    $regEntry = Get-ItemProperty $regPath -ErrorAction Stop
                    if ($regEntry.InstalledDirectory) {
                        $candidate = Join-Path $regEntry.InstalledDirectory "Engine\Binaries\ThirdParty\Python3\Win64\python.exe"
                        if (Test-Path $candidate) {
                            $UEPython = $candidate
                            Write-Host "  [registry HKLM] $UEPython" -ForegroundColor DarkGray
                        }
                    }
                } catch {}

                # Try HKCU custom builds (source builds register GUIDs here)
                if (-not $UEPython) {
                    try {
                        $builds = Get-ItemProperty "HKCU:\SOFTWARE\Epic Games\Unreal Engine\Builds" -ErrorAction Stop
                        $builds.PSObject.Properties | Where-Object { $_.Name -notmatch '^PS' } | ForEach-Object {
                            if (-not $UEPython) {
                                $buildPath = $_.Value
                                # If EngineAssociation is a GUID, the property name is the GUID
                                # If it's a version like "5.7", check if the path contains it
                                if ($_.Name -eq $engineVer -or $buildPath -match [regex]::Escape($engineVer)) {
                                    $candidate = Join-Path $buildPath "Engine\Binaries\ThirdParty\Python3\Win64\python.exe"
                                    if (Test-Path $candidate) {
                                        $UEPython = $candidate
                                        Write-Host "  [registry HKCU] $UEPython" -ForegroundColor DarkGray
                                    }
                                }
                            }
                        }
                    } catch {}
                }
            }
        } catch {}
        if ($UEPython) { break }
    }
}

# --- Priority 3: Parse .code-workspace file for engine folder ---
if (-not $UEPython) {
    $workspaceFiles = Get-ChildItem -Path $ProjectRoot -Filter "*.code-workspace" -ErrorAction SilentlyContinue
    foreach ($wsFile in $workspaceFiles) {
        try {
            $wsContent = Get-Content $wsFile.FullName -Raw | ConvertFrom-Json
            foreach ($folder in $wsContent.folders) {
                $folderPath = $folder.path
                # Look for folders referencing UE engine (contain "UE_" or "Engine")
                if ($folderPath -match "UE_\d|Unreal.?Engine|EpicGame") {
                    $absPath = if ([System.IO.Path]::IsPathRooted($folderPath)) { $folderPath } else { Join-Path $ProjectRoot $folderPath }
                    $candidate = Join-Path $absPath "Engine\Binaries\ThirdParty\Python3\Win64\python.exe"
                    if (Test-Path $candidate) {
                        $UEPython = $candidate
                        Write-Host "  [.code-workspace] $UEPython" -ForegroundColor DarkGray
                        break
                    }
                }
            }
        } catch {}
        if ($UEPython) { break }
    }
}

# --- Priority 4: UE_ENGINE_DIR environment variable ---
if (-not $UEPython -and $env:UE_ENGINE_DIR) {
    $candidate = Join-Path $env:UE_ENGINE_DIR "Binaries\ThirdParty\Python3\Win64\python.exe"
    if (Test-Path $candidate) {
        $UEPython = $candidate
        Write-Host "  [env UE_ENGINE_DIR] $UEPython" -ForegroundColor DarkGray
    }
}

# --- Priority 5: Scan common installation directories ---
if (-not $UEPython) {
    # Build list of candidate drives
    $drives = @("C:", "D:", "E:", "F:")
    $patterns = @(
        "{0}\EpicGame\UE_*",
        "{0}\Program Files\Epic Games\UE_*",
        "{0}\UnrealEngine\UE_*"
    )
    foreach ($drive in $drives) {
        if (-not (Test-Path "$drive\")) { continue }
        foreach ($pattern in $patterns) {
            $globPath = $pattern -f $drive
            $found = Get-ChildItem -Path $globPath -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending
            foreach ($dir in $found) {
                $candidate = Join-Path $dir.FullName "Engine\Binaries\ThirdParty\Python3\Win64\python.exe"
                if (Test-Path $candidate) {
                    $UEPython = $candidate
                    Write-Host "  [disk scan] $UEPython" -ForegroundColor DarkGray
                    break
                }
            }
            if ($UEPython) { break }
        }
        if ($UEPython) { break }
    }
}

if (-not $UEPython) {
    Write-Host ""
    Write-Host "  Could not auto-detect UE Engine Python." -ForegroundColor Red
    Write-Host "  Re-run with: .\setup_mcp.ps1 -EngineRoot 'E:\EpicGame\UE_5.7'" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

Write-Host "  Found: $UEPython" -ForegroundColor Green
$version = & $UEPython --version 2>&1
Write-Host "  Version: $version" -ForegroundColor Green
Write-Host ""

# --- Step 2: Create virtual environment ---
Write-Host "[2/4] Creating virtual environment..." -ForegroundColor Yellow

if (Test-Path $VenvDir) {
    Write-Host "  Removing existing venv..."
    Remove-Item -Recurse -Force $VenvDir
}

$prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& $UEPython -m venv $VenvDir 2>&1 | Out-Null
$ErrorActionPreference = $prevEAP
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Failed to create virtual environment." -ForegroundColor Red
    exit 1
}
Write-Host "  Created: $VenvDir" -ForegroundColor Green
Write-Host ""

# --- Step 3: Install dependencies ---
Write-Host "[3/4] Installing MCP package..." -ForegroundColor Yellow

$pipExe = Join-Path $VenvDir "Scripts\pip.exe"
$reqFile = Join-Path $PythonDir "requirements.txt"
$vendorDir = Join-Path $PythonDir "vendor"
$installed = $false

# 辅助函数：运行 pip 并实时显示输出，带总超时保护
function Invoke-PipInstall {
    param(
        [string]$PipExePath,
        [string[]]$Arguments,
        [int]$TimeoutSeconds = 600   # 整体进程超时（默认 10 分钟）
    )
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName  = $PipExePath
    $psi.Arguments = $Arguments -join ' '
    $psi.UseShellExecute = $false
    # 不重定向输出，让 pip 直接打印到控制台（进度条 + 日志实时可见）
    $psi.RedirectStandardOutput = $false
    $psi.RedirectStandardError  = $false

    $proc = [System.Diagnostics.Process]::Start($psi)

    $exited = $proc.WaitForExit($TimeoutSeconds * 1000)
    if (-not $exited) {
        try { $proc.Kill() } catch {}
        Write-Host "  ERROR: pip process timed out after $TimeoutSeconds seconds." -ForegroundColor Red
        return 124   # 仿 Linux timeout 退出码
    }

    return $proc.ExitCode
}

# 优先离线 vendor 安装（稳定、快速、无网络依赖）
if (Test-Path $vendorDir) {
    Write-Host "  Trying offline vendor wheels first..." -ForegroundColor DarkGray
    $offlineArgs = @('install', '-r', "`"$reqFile`"", '--no-index', '--find-links', "`"$vendorDir`"")
    $exitCode = Invoke-PipInstall -PipExePath $pipExe -Arguments $offlineArgs -TimeoutSeconds 300
    if ($exitCode -eq 0) {
        $installed = $true
        Write-Host "  Dependencies installed (offline vendor)." -ForegroundColor Green
    } else {
        Write-Host "  Offline vendor install failed (exit=$exitCode), will try online..." -ForegroundColor Yellow
    }
}

# 离线失败或无 vendor 目录 → 在线回退
if (-not $installed) {
    Write-Host "  Trying online install (timeout per-socket=120s, process=600s)..." -ForegroundColor DarkGray
    $onlineArgs = @('install', '-r', "`"$reqFile`"", '--retries', '3', '--timeout', '120', '--progress-bar', 'on')
    $exitCode2 = Invoke-PipInstall -PipExePath $pipExe -Arguments $onlineArgs -TimeoutSeconds 600
    if ($exitCode2 -eq 0) {
        $installed = $true
        Write-Host "  Dependencies installed (online)." -ForegroundColor Green
    } else {
        Write-Host "  Online install also failed (exit=$exitCode2)." -ForegroundColor Yellow
    }
}

if (-not $installed) {
    Write-Host "  ERROR: Failed to install dependencies (online & offline)." -ForegroundColor Red
    Write-Host "  Run scripts\Download-Wheels.ps1 to prepare offline packages." -ForegroundColor Yellow
    exit 1
}
Write-Host ""

# --- Step 4: Upsert mcp.json (merge into existing client configs) ---
Write-Host "[4/4] Updating MCP client config(s)..." -ForegroundColor Yellow

$venvPython = (Join-Path $VenvDir "Scripts\python.exe").Replace('\', '/')
$pythonPath = $PythonDir.Replace('\', '/')

# Our UEEditorMCP servers — definitions are reused for every target client.
# ue-dev-loop-mcp 只做开发闭环计划/评估；编译、启动、跑测仍由 launcher 服务负责。
function New-UeMcpServerSpec
{
    param(
        [string]$Module,
        [string]$VenvPython,
        [string]$PythonPath
    )
    $envSpec = [pscustomobject]@{ PYTHONPATH = $PythonPath }
    [pscustomobject]@{
        command = $VenvPython
        args    = @('-m', $Module)
        env     = $envSpec
    }
}

$ueServers = @{
    'ue-editor-mcp'          = New-UeMcpServerSpec -Module 'ue_editor_mcp.server_unified'      -VenvPython $venvPython -PythonPath $pythonPath
    'ue-editor-mcp-logs'     = New-UeMcpServerSpec -Module 'ue_editor_mcp.server_unreal_logs'  -VenvPython $venvPython -PythonPath $pythonPath
    'ue-editor-mcp-launcher' = New-UeMcpServerSpec -Module 'ue_editor_mcp.server_launcher'     -VenvPython $venvPython -PythonPath $pythonPath
    'ue-dev-loop-mcp'        = New-UeMcpServerSpec -Module 'ue_editor_mcp.server_dev_loop'     -VenvPython $venvPython -PythonPath $pythonPath
}

function Get-UserHomePath {
    $candidates = @(
        $env:USERPROFILE,
        $HOME,
        [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    foreach ($candidate in $candidates) {
        $resolved = Resolve-Path -LiteralPath $candidate -ErrorAction SilentlyContinue
        if ($resolved) { return $resolved.Path }
    }
    return $null
}

# Candidate target files. Each entry: Path + which top-level key the file uses.
# Order matters — we touch every existing file; if none exist we create the
# project-local one (VS Code Copilot default).
$targets = New-Object System.Collections.Generic.List[object]
$targets.Add([pscustomobject]@{
    Path = (Join-Path $ProjectRoot ".vscode\mcp.json")
    Key = 'servers'
    Label = 'VS Code Copilot (project)'
    Create = $true
}) | Out-Null

$userHomePath = Get-UserHomePath
if ($userHomePath) {
    $targets.Add([pscustomobject]@{
        Path = (Join-Path $userHomePath ".gongfeng-copilot\mcp.json")
        Key = 'mcpServers'
        Label = 'gongfeng-copilot (user)'
        Create = $true
    }) | Out-Null
    $targets.Add([pscustomobject]@{
        Path = (Join-Path $userHomePath ".codebuddy\mcp.json")
        Key = 'mcpServers'
        Label = 'CodeBuddy (user)'
        Create = $true
    }) | Out-Null

    $cursorDir = Join-Path $userHomePath ".cursor"
    if (Test-Path $cursorDir) {
        $targets.Add([pscustomobject]@{
            Path = (Join-Path $cursorDir "mcp.json")
            Key = 'mcpServers'
            Label = 'Cursor (user)'
            Create = $false
        }) | Out-Null
    }
}

if (-not [string]::IsNullOrWhiteSpace($env:APPDATA)) {
    $vscodeUserDir = Join-Path $env:APPDATA "Code\User"
    if (Test-Path $vscodeUserDir) {
        $targets.Add([pscustomobject]@{
            Path = (Join-Path $vscodeUserDir "mcp.json")
            Key = 'servers'
            Label = 'VS Code Copilot (user)'
            Create = $false
        }) | Out-Null
    }
}

function ConvertTo-OrderedHashtable {
    param($Obj)
    if ($null -eq $Obj) { return [ordered]@{} }
    $h = [ordered]@{}
    foreach ($prop in $Obj.PSObject.Properties) { $h[$prop.Name] = $prop.Value }
    return $h
}

function Update-McpConfigFile {
    param(
        [string]$Path,
        [string]$TopKey,
        [string]$Label,
        [hashtable]$ServersToUpsert
    )

    $exists = Test-Path $Path
    $root = $null
    if ($exists) {
        try {
            $rawJson = Get-Content $Path -Raw -ErrorAction Stop
            if (-not [string]::IsNullOrWhiteSpace($rawJson)) {
                $root = $rawJson | ConvertFrom-Json -ErrorAction Stop
            }
        } catch {
            Write-Host "  [$Label] WARN existing file unreadable, skipping ($($_.Exception.Message))" -ForegroundColor Yellow
            return $false
        }
    }

    if ($null -eq $root) { $root = [pscustomobject]@{} }

    # Pick top-level key. If file exists with the OTHER convention, respect it.
    $effectiveKey = $TopKey
    if ($root.PSObject.Properties.Name -contains 'mcpServers') { $effectiveKey = 'mcpServers' }
    elseif ($root.PSObject.Properties.Name -contains 'servers') { $effectiveKey = 'servers' }

    $existingServers = $null
    if ($root.PSObject.Properties.Name -contains $effectiveKey) {
        $existingServers = $root.$effectiveKey
    }
    $serversMap = ConvertTo-OrderedHashtable $existingServers

    $changed = $false
    foreach ($name in $ServersToUpsert.Keys) {
        $newSpec = $ServersToUpsert[$name]
        if ($serversMap.Contains($name)) {
            $oldJson = $serversMap[$name] | ConvertTo-Json -Depth 6 -Compress
            $newJson = $newSpec            | ConvertTo-Json -Depth 6 -Compress
            if ($oldJson -ne $newJson) {
                $serversMap[$name] = $newSpec
                $changed = $true
            }
        } else {
            $serversMap[$name] = $newSpec
            $changed = $true
        }
    }

    if (-not $changed -and $exists) {
        Write-Host "  [$Label] up-to-date: $Path" -ForegroundColor DarkGray
        return $true
    }

    # Rebuild root preserving non-server keys
    $newRoot = [ordered]@{}
    foreach ($prop in $root.PSObject.Properties) {
        if ($prop.Name -ne 'servers' -and $prop.Name -ne 'mcpServers') {
            $newRoot[$prop.Name] = $prop.Value
        }
    }
    $newRoot[$effectiveKey] = $serversMap

    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $jsonOut = ($newRoot | ConvertTo-Json -Depth 8)
    [System.IO.File]::WriteAllText($Path, $jsonOut, [System.Text.UTF8Encoding]::new($false))
    Write-Host "  [$Label] updated: $Path" -ForegroundColor Green
    return $true
}

function Format-TomlString {
    param([string]$Value)
    return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
}

function Format-TomlStringArray {
    param([object[]]$Values)
    $items = @($Values | ForEach-Object { Format-TomlString ([string]$_) })
    return "[" + ($items -join ", ") + "]"
}

function Remove-TomlSection {
    param(
        [string]$Content,
        [string]$SectionName
    )
    $escaped = [regex]::Escape($SectionName)
    return [regex]::Replace($Content, "(?ms)^\[$escaped\]\r?\n.*?(?=^\[|\z)", "").TrimEnd()
}

function Get-CodexConfigPath {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        $candidates += (Join-Path $env:CODEX_HOME "config.toml")
    }

    $userHome = Get-UserHomePath
    if ($userHome) {
        $candidates += (Join-Path $userHome ".codex\config.toml")
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Path $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        return (Join-Path ([System.IO.Path]::GetFullPath($env:CODEX_HOME)) "config.toml")
    }
    if ($userHome) {
        return (Join-Path $userHome ".codex\config.toml")
    }
    return $null
}

function Get-EnvKeys {
    param($EnvObj)
    if ($EnvObj -is [System.Collections.IDictionary]) {
        return $EnvObj.Keys
    }
    return @($EnvObj.PSObject.Properties.Name)
}

function Get-EnvValue {
    param($EnvObj, [string]$Key)
    if ($EnvObj -is [System.Collections.IDictionary]) {
        return $EnvObj[$Key]
    }
    return $EnvObj.$Key
}

function Update-CodexMcpConfigFile {
    param(
        [string]$Path,
        [hashtable]$ServersToUpsert
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        Write-Host "  [Codex] WARN user profile not detected, skipping" -ForegroundColor Yellow
        return $false
    }

    $content = ""
    if (Test-Path $Path) {
        $content = Get-Content $Path -Raw -Encoding UTF8
    }

    foreach ($name in $ServersToUpsert.Keys) {
        $content = Remove-TomlSection -Content $content -SectionName "mcp_servers.$name"
        $content = Remove-TomlSection -Content $content -SectionName "mcp_servers.$name.env"
    }

    $blocks = New-Object System.Collections.Generic.List[string]
    foreach ($name in ($ServersToUpsert.Keys | Sort-Object)) {
        $server = $ServersToUpsert[$name]
        $lines = New-Object System.Collections.Generic.List[string]
        $lines.Add("[mcp_servers.$name]") | Out-Null
        $lines.Add("command = $(Format-TomlString $server.command)") | Out-Null
        $lines.Add("args = $(Format-TomlStringArray $server.args)") | Out-Null
        $lines.Add("enabled = true") | Out-Null
        $lines.Add("") | Out-Null
        $lines.Add("[mcp_servers.$name.env]") | Out-Null
        foreach ($envName in ((Get-EnvKeys $server.env) | Sort-Object)) {
            $lines.Add("$envName = $(Format-TomlString ([string](Get-EnvValue $server.env $envName)))") | Out-Null
        }
        $blocks.Add(($lines -join "`r`n")) | Out-Null
    }

    $newContent = $content.TrimEnd()
    if (-not [string]::IsNullOrWhiteSpace($newContent)) {
        $newContent += "`r`n`r`n"
    }
    $newContent += (($blocks.ToArray()) -join "`r`n`r`n") + "`r`n"

    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $newContent, [System.Text.UTF8Encoding]::new($false))
    Write-Host "  [Codex] updated: $Path" -ForegroundColor Green
    return $true
}

$touched = $false
foreach ($t in $targets) {
    if ([bool]$t.Create -or (Test-Path $t.Path)) {
        if (Update-McpConfigFile -Path $t.Path -TopKey $t.Key -Label $t.Label -ServersToUpsert $ueServers) {
            $touched = $true
        }
    }
}

# Fallback: if no client config existed, create the project-local VS Code one
if (-not $touched) {
    $defaultPath = Join-Path $ProjectRoot ".vscode\mcp.json"
    Update-McpConfigFile -Path $defaultPath -TopKey 'servers' -Label 'VS Code Copilot (project, new)' -ServersToUpsert $ueServers | Out-Null
}

Update-CodexMcpConfigFile -Path (Get-CodexConfigPath) -ServersToUpsert $ueServers | Out-Null

Write-Host ""

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Setup Complete!" -ForegroundColor Cyan
Write-Host " No external Python installation needed." -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host " Next steps:" -ForegroundColor Yellow
Write-Host "   1. Open your UE project in the Editor"
Write-Host "   2. Open VS Code - ue-editor-mcp / -logs / -launcher / -dev-loop servers will auto-start"
Write-Host "   3. Use Copilot Chat to control Blueprints"
Write-Host "   4. (First time only) launcher server auto-creates <ProjectRoot>/.uemcp/launcher.json"
Write-Host ""
