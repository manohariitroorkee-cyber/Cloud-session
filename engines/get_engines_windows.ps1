# Download the ready-built Windows engines (epanet2.dll, swmm5.dll) into engines\lib\.
# They are built from source and published by the repository's own "platform" workflow.
$ErrorActionPreference = "Stop"
$Lib = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "lib"
$Zip = Join-Path $env:TEMP "engines-windows.zip"
New-Item -ItemType Directory -Force -Path $Lib | Out-Null
Invoke-WebRequest -UseBasicParsing "https://github.com/manohariitroorkee-cyber/Cloud-session/releases/download/engines-windows/engines-windows.zip" -OutFile $Zip
Expand-Archive -Force $Zip $Lib
Get-ChildItem $Lib
