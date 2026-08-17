# Regenerate bun.lock FROM SCRATCH for the Windows [[regenerate]] rule.
$ErrorActionPreference = "Stop"

# Refuse before removing the existing lock. check-tools resolves PowerShell,
# not the bun process launched inside this helper.
$bun = Get-Command bun -ErrorAction SilentlyContinue
if ($null -eq $bun) {
    Write-Error "regen-bun-lock: bun not found"
    exit 127
}

Remove-Item -LiteralPath "bun.lock" -Force -ErrorAction SilentlyContinue
& $bun.Source install
exit $LASTEXITCODE
