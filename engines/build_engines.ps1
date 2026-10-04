# Build the calculation engines on Windows into engines\lib\ (epanet2.dll, swmm5.dll).
# Needs: Git, CMake and "Visual Studio Build Tools" (C++ workload). Run from the repository folder:
#   powershell -ExecutionPolicy Bypass -File engines\build_engines.ps1
# Ready-built DLLs are also produced by the "windows" job of the platform workflow (artifact engines-windows).
$ErrorActionPreference = "Stop"
$Here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root  = Split-Path -Parent $Here
$Lib   = Join-Path $Here "lib"
$Build = Join-Path $Here ".build"
$Tag   = if ($env:SWMM_TAG) { $env:SWMM_TAG } else { "v5.2.4" }
New-Item -ItemType Directory -Force -Path $Lib, $Build | Out-Null

Write-Host "== EPANET (repository source)"
cmake -S $Root -B "$Build\epanet" -A x64
cmake --build "$Build\epanet" --target epanet2 --config Release
Get-ChildItem -Recurse "$Build\epanet" -Filter epanet2.dll | Select-Object -First 1 | Copy-Item -Destination $Lib

Write-Host "== EPA SWMM $Tag (official USEPA source)"
if (-not (Test-Path "$Build\swmm-src\.git")) {
  git clone --depth 1 --branch $Tag https://github.com/USEPA/Stormwater-Management-Model "$Build\swmm-src"
}
cmake -S "$Build\swmm-src" -B "$Build\swmm" -A x64
cmake --build "$Build\swmm" --target swmm5 --config Release
Get-ChildItem -Recurse "$Build\swmm" -Filter swmm5.dll | Select-Object -First 1 | Copy-Item -Destination $Lib

Write-Host "== Engines in $Lib"
Get-ChildItem $Lib
