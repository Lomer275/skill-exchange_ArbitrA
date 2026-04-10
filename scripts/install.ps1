# Manual skill installation without CLI.
# Usage: .\scripts\install.ps1 <skill-name> [target-dir]
#
# Examples:
#   .\scripts\install.ps1 git-commit-helper
#   .\scripts\install.ps1 git-commit-helper C:\Users\me\.claude\plugins

param(
    [Parameter(Mandatory=$true)]
    [string]$SkillName,

    [string]$TargetDir = "$env:USERPROFILE\.claude\plugins"
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SkillsDir = Join-Path $RepoRoot "skills"
$SkillSrc  = Join-Path $SkillsDir $SkillName

if (-not (Test-Path $SkillSrc)) {
    Write-Error "Skill '$SkillName' not found in $SkillsDir"
    Write-Host "Available skills:"
    Get-ChildItem $SkillsDir -Directory | Select-Object -ExpandProperty Name
    exit 1
}

New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
$Dest = Join-Path $TargetDir $SkillName
if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
Copy-Item -Recurse $SkillSrc $Dest

Write-Host "Skill '$SkillName' installed to $Dest"
Write-Host "Restart Claude Code to apply."
