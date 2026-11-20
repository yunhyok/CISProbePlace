$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

python -m PyInstaller `
  --noconfirm `
  .\CISProbePlacementScriptor.spec

# A failing native command does not stop the script on its own, so report it
# explicitly; otherwise the installer step would package a stale dist folder.
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
