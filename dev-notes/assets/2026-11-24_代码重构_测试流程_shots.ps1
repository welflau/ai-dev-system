<#
在独立的控制台窗口里运行命令，跑完后只截那个窗口，存成 PNG。
用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File <本文件>              # 全部截一遍
  powershell -NoProfile -ExecutionPolicy Bypass -File <本文件> -Only 01,03  # 只截指定编号
说明：
  - 窗口用 conhost.exe 打开，截图用 PrintWindow，只取这一个窗口，不截桌面上的其他内容。
  - 每条命令前的「PS 路径> 命令」和命令后的灰色「[时间 退出码 用时]」两行是本脚本打印的（只有不带管道的外部程序才显示退出码），其余都是命令自己的输出。
  - flake8 来自 $env:ADS_FLAKE8_DIR 指向的目录；改坏检查脚本来自 $env:ADS_MUT_DIR。两者都不在仓库里。
  - 本文件带 BOM：Windows PowerShell 5.1 读不带 BOM 的中文脚本会乱码。
#>
param([string[]]$Only, [string]$ChildJob, [string]$Marker)

# 用 -File 调用时 "01,03" 会作为一个字符串传进来，这里拆开
if ($Only) { $Only = @($Only | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Prefix = "2026-11-24_代码重构_测试流程_截图"
if (-not $env:ADS_FLAKE8_DIR) { $env:ADS_FLAKE8_DIR = Join-Path $env:TEMP "ads_r2_3\venv312\Scripts" }
if (-not $env:ADS_MUT_DIR) { $env:ADS_MUT_DIR = Join-Path $env:TEMP "ads_r2_3" }

$Jobs = [ordered]@{
  "01" = @{ Name = "相关测试文件"; Dir = "backend"; Cols = 118; Lines = 12; Timeout = 120; Cmds = @(
      'python -m pytest tests/agents/test_orchestrator_handle_requirement.py tests/agents/test_prd_analysis_progress.py -p no:cacheprovider') }
  "02" = @{ Name = "全量pytest"; Dir = "backend"; Cols = 96; Lines = 24; Timeout = 900; Cmds = @(
      'python -m pytest -p no:cacheprovider') }
  "03" = @{ Name = "分层守卫"; Dir = "."; Cols = 118; Lines = 32; Timeout = 120; Cmds = @(
      'python scripts/check_layers.py') }
  "04" = @{ Name = "flake8"; Dir = "backend"; Cols = 118; Lines = 9; Timeout = 300; Path = $env:ADS_FLAKE8_DIR; Cmds = @(
      'flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=skills/marketplace,skills/packs,skills/use_skills,projects') }
  "05" = @{ Name = "自动化现状"; Dir = "."; Cols = 120; Lines = 28; Timeout = 120; Cmds = @(
      'Get-ChildItem .git\hooks | Where-Object { $_.Name -notlike "*.sample" } | Measure-Object | Select-Object -ExpandProperty Count',
      'git config --get core.hooksPath',
      'python -c "import importlib.util as u; print(u.find_spec(''pre_commit''))"',
      'git rev-parse --abbrev-ref --symbolic-full-name "@{u}"',
      'git rev-list --count "@{u}..HEAD"',
      'git diff --stat HEAD -- .github/workflows/ci.yml') }
  "06" = @{ Name = "改坏检查三处"; Dir = "."; Cols = 132; Lines = 27; Timeout = 300; Cmds = @(
      '$env:ADS_MUT_ONLY = "split: milestone/branch swapped|split: timeout not shared|split: heartbeat text changed"',
      '$env:ADS_MUT_OUT = "$env:TEMP\ads_mut_demo.txt"',
      'python "$env:ADS_MUT_DIR\mutate_req.py"',
      'Get-Content -Encoding utf8 $env:ADS_MUT_OUT',
      'Get-FileHash backend\orchestrator.py, backend\orchestration\requirement_pipeline.py | ForEach-Object { $_.Hash.Substring(0,16).ToLower() }') }
}

if ($ChildJob) {
  $j = $Jobs[$ChildJob]
  $Host.UI.RawUI.WindowTitle = "ads-shot-$ChildJob"
  cmd /c "mode con: cols=$($j.Cols) lines=$($j.Lines)" | Out-Null
  if ($j.Path) { $env:PATH = "$($j.Path);$env:PATH" }
  $env:GIT_PAGER = "cat"
  Set-Location (Join-Path $Repo $j.Dir)
  $first = $true
  foreach ($c in $j.Cmds) {
    if (-not $first) { Write-Host "" }
    $first = $false
    Write-Host "PS $((Get-Location).Path)> " -NoNewline
    Write-Host $c -ForegroundColor Yellow
    $global:LASTEXITCODE = 0
    $sw = [Diagnostics.Stopwatch]::StartNew()
    # 外部程序且没有管道时直接连着控制台跑，保留它自己的颜色和退出码；其余的交给 Out-Host 保证输出顺序
    $native = ($c -match '^(python|git|flake8) ') -and ($c -notmatch '\|')
    if ($native) { & ([scriptblock]::Create($c)) } else { Invoke-Expression $c | Out-Host }
    $sw.Stop()
    if ($c -match '^\$env:') { continue }
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    if ($native) { Write-Host ("[{0}  退出码 {1}  用时 {2:n1} 秒]" -f $stamp, $LASTEXITCODE, $sw.Elapsed.TotalSeconds) -ForegroundColor DarkGray }
    else { Write-Host ("[{0}  用时 {1:n1} 秒]" -f $stamp, $sw.Elapsed.TotalSeconds) -ForegroundColor DarkGray }
  }
  Set-Content -Path $Marker -Value "done"
  Start-Sleep -Seconds 600
  exit
}

Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System; using System.Drawing; using System.Drawing.Imaging; using System.Runtime.InteropServices;
public static class WinShot {
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr FindWindow(string c, string t);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
  [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr h, int a, out RECT r, int s);
  [StructLayout(LayoutKind.Sequential)] struct RECT { public int L, T, R, B; }
  public static void Init() { SetProcessDPIAware(); }
  public static string Capture(string title, string path) {
    IntPtr h = FindWindow(null, title);
    if (h == IntPtr.Zero) return "nowindow";
    // 窗口被最小化时先还原（不抢焦点），否则只能截到任务栏按钮大小的一条
    if (IsIconic(h)) { ShowWindow(h, 4); System.Threading.Thread.Sleep(700); }
    RECT w; GetWindowRect(h, out w);
    RECT f; if (DwmGetWindowAttribute(h, 9, out f, 16) != 0) f = w;
    int W = w.R - w.L, H = w.B - w.T;
    using (var bmp = new Bitmap(W, H, PixelFormat.Format32bppArgb)) {
      bool ok;
      using (var g = Graphics.FromImage(bmp)) { IntPtr dc = g.GetHdc(); ok = PrintWindow(h, dc, 2); g.ReleaseHdc(dc); }
      var crop = Rectangle.Intersect(new Rectangle(f.L - w.L, f.T - w.T, f.R - f.L, f.B - f.T), new Rectangle(0, 0, W, H));
      using (var c = bmp.Clone(crop, bmp.PixelFormat)) c.Save(path, ImageFormat.Png);
      return (ok ? "ok " : "printwindow-failed ") + crop.Width + "x" + crop.Height;
    }
  }
}
"@
[WinShot]::Init()

foreach ($id in $Jobs.Keys) {
  if ($Only -and ($Only -notcontains $id)) { continue }
  $j = $Jobs[$id]
  $out = Join-Path $PSScriptRoot ("{0}_{1}_{2}.png" -f $Prefix, $id, $j.Name)
  $mk = Join-Path $env:TEMP "ads_shot_$id.marker"
  Remove-Item $mk -ErrorAction SilentlyContinue
  $p = Start-Process conhost.exe -PassThru -ArgumentList @("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-ChildJob", $id, "-Marker", "`"$mk`"")
  $deadline = (Get-Date).AddSeconds($j.Timeout)
  while (-not (Test-Path $mk) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
  $done = Test-Path $mk
  Start-Sleep -Milliseconds 900
  $r = [WinShot]::Capture("ads-shot-$id", $out)
  & taskkill /PID $p.Id /T /F 2>&1 | Out-Null
  Remove-Item $mk -ErrorAction SilentlyContinue
  "{0} done={1} {2} {3}" -f $id, $done, $r, $out
}
