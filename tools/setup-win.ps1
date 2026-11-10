# Rhino Open AI Kit - one-time setup for Windows (called by setup-win.bat)
# Picks a preset for this PC, downloads the pinned llama.cpp runtime and the model,
# and checks every download against its SHA-256 checksum. Afterwards the kit runs offline.
param([string]$Preset = "")
$ErrorActionPreference = "Stop"
$Kit = Split-Path -Parent $PSScriptRoot
Set-Location $Kit

# Pinned llama.cpp release (tested build). Hashes from the GitHub release page.
$Build = "b12255"
$Base  = "https://github.com/ggml-org/llama.cpp/releases/download/$Build"
$Runtimes = @{
  "win-cuda"   = @(@("llama-$Build-bin-win-cuda-12.4-x64.zip", "f8612e0f13bb7dfa6dfa7fd8b6a70f626898c10a4476c73e4295db5dc48bf226"),
                   @("cudart-llama-bin-win-cuda-12.4-x64.zip", "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"))
  "win-vulkan" = @(,@("llama-$Build-bin-win-vulkan-x64.zip",   "12460d097486a06eb1c3b745194eb1436d315bcc23003a74a40a11e2721167c8"))
  "win-cpu"    = @(,@("llama-$Build-bin-win-cpu-x64.zip",      "ec06d7b2f3fc4f7cff3e395e3e85c0de5f928b6a62a8647bbf85776351385597"))
}

function Fail($msg) { Write-Host ""; Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
function Sha($path) { (Get-FileHash -Algorithm SHA256 $path).Hash.ToLower() }
function ReadConf($path) {
  $c = @{}
  foreach ($line in Get-Content $path) {
    $t = $line.Trim()
    if ($t -eq "" -or $t.StartsWith("#") -or -not $t.Contains("=")) { continue }
    $k, $v = $t.Split("=", 2); $c[$k.Trim()] = $v.Trim()
  }
  return $c
}

# ------------------------------------------------------------- 1. preset
$ramGB = [math]::Floor((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
$vramGB = 0; $nvidia = $false
try {
  $mb = & nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1
  if ($mb) { $vramGB = [math]::Floor([int]$mb / 1024); $nvidia = $true }
} catch {}
if (-not $nvidia) {
  # AMD / Intel: dedicated memory is not reported reliably, so ask
  $gpu = (Get-CimInstance Win32_VideoController | Select-Object -First 1).Name
}
if     ($vramGB -ge 22) { $rec = "win-gpu-24gb" }
elseif ($vramGB -ge 15) { $rec = "win-gpu-16gb" }
elseif ($vramGB -ge 11) { $rec = "win-gpu-12gb" }
elseif ($vramGB -ge 7)  { $rec = "win-gpu-8gb" }
else                    { $rec = "win-cpu" }

if ($Preset -eq "") {
  if ($nvidia) { Write-Host "This PC: $ramGB GB RAM, NVIDIA GPU with $vramGB GB VRAM. Recommended: $rec" }
  else { Write-Host "This PC: $ramGB GB RAM, GPU: $gpu (no NVIDIA found). Recommended: $rec"
         Write-Host "With an AMD/Intel GPU, pick a win-gpu preset that fits its memory; setup then uses Vulkan." }
  Write-Host ""
  Get-ChildItem "presets\win-*.conf" | ForEach-Object {
    $label = (Get-Content $_.FullName -TotalCount 1) -replace "^# Preset: ", ""
    Write-Host ("  {0,-13} {1}" -f $_.BaseName, $label)
  }
  Write-Host "  keep          keep the current kit.conf"
  Write-Host ""
  $Preset = Read-Host "Preset [$rec]"
  if ($Preset -eq "") { $Preset = $rec }
}

if ($Preset -ne "keep") {
  $src = "presets\$Preset.conf"
  if (-not (Test-Path $src)) { Fail "No preset $src" }
  if (Test-Path "kit.conf") { Copy-Item "kit.conf" "kit.conf.bak" -Force }
  $text = Get-Content $src -Raw
  if (-not $nvidia -and $Preset -ne "win-cpu") { $text = $text -replace "(?m)^BACKEND=.*$", "BACKEND=win-vulkan" }
  [IO.File]::WriteAllText((Join-Path $Kit "kit.conf"), ($text -replace "`r`n", "`n"))
  Write-Host "kit.conf set to preset $Preset (old one saved as kit.conf.bak)."
}
$conf = ReadConf "kit.conf"

# ------------------------------------------------------------- 2. runtime
$server = Get-ChildItem "bin\win" -Recurse -Filter "llama-server.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $server) {
  $backend = $conf["BACKEND"]; if (-not $Runtimes.ContainsKey($backend)) { $backend = "win-cpu" }
  $tmp = Join-Path $env:TEMP ("roak-" + [guid]::NewGuid())
  New-Item -ItemType Directory $tmp | Out-Null
  $first = $true
  foreach ($pair in $Runtimes[$backend]) {
    $file, $want = $pair
    Write-Host ""; Write-Host "Downloading llama.cpp $Build ($file) ..."
    & curl.exe -fL --progress-bar -o "$tmp\$file" "$Base/$file"
    if ($LASTEXITCODE -ne 0) { Fail "Download failed." }
    if ((Sha "$tmp\$file") -ne $want) { Remove-Item $tmp -Recurse -Force; Fail "Checksum mismatch for $file. Nothing installed." }
    if ($first) {
      Expand-Archive "$tmp\$file" -DestinationPath "bin\win" -Force
      $server = Get-ChildItem "bin\win" -Recurse -Filter "llama-server.exe" | Select-Object -First 1
      if (-not $server) { Fail "llama-server.exe not found in $file" }
      $first = $false
    } else {
      # CUDA runtime DLLs go next to llama-server.exe
      Expand-Archive "$tmp\$file" -DestinationPath $server.DirectoryName -Force
    }
  }
  Remove-Item $tmp -Recurse -Force
  Write-Host "Runtime installed in bin\win (checksums OK)."
} else { Write-Host "Runtime already in bin\win." }

# ------------------------------------------------------------- 3. model
# Hugging Face sends each file's SHA-256 in the x-linked-etag header.
function FetchHF($rel, $local) {
  if (-not $local) { $local = $rel }
  $url = "https://huggingface.co/$($conf['MODEL_REPO'])/resolve/main/$rel"
  $dst = Join-Path "models" $local
  if (Test-Path $dst) { Write-Host "Have models\$local"; return }
  New-Item -ItemType Directory -Force (Split-Path -Parent $dst) | Out-Null
  $head = & curl.exe -sI $url
  $want = ($head | Where-Object { $_ -match '^x-linked-etag:\s*"?([0-9a-f]{64})' } | ForEach-Object { $Matches[1] }) | Select-Object -First 1
  Write-Host ""; Write-Host "Downloading $rel from $($conf['MODEL_REPO']) ..."
  & curl.exe -fL -C - --progress-bar -o "$dst.part" $url
  if ($LASTEXITCODE -ne 0) { Fail "Download failed. Run setup again to resume." }
  if ($want) {
    if ((Sha "$dst.part") -ne $want) { Remove-Item "$dst.part"; Fail "Checksum mismatch for $rel. Deleted." }
    Write-Host "Checksum OK."
  } else { Write-Host "Note: no checksum offered by the server for $rel, not verified." }
  Move-Item "$dst.part" $dst
}

$parts = 1; if ($conf["MODEL_PARTS"]) { $parts = [int]$conf["MODEL_PARTS"] }
if ($parts -gt 1) {
  for ($i = 1; $i -le $parts; $i++) {
    FetchHF ($conf["MODEL"] -replace "-00001-of-", ("-{0:D5}-of-" -f $i)) $null
  }
} else { FetchHF $conf["MODEL"] $null }
if ($conf["MMPROJ"]) {
  $mf = $conf["MMPROJ_FILE"]; if (-not $mf) { $mf = "mmproj-F16.gguf" }
  FetchHF $mf $conf["MMPROJ"]
}

Write-Host ""
Write-Host "Setup done. In Rhino 8 run _-RunPythonScript and pick rhino\rhino_ai.py"
