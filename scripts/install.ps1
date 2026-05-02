# Manual skill installation without CLI (fallback for users without Python).
# Copies SKILL.md + README.md to <target>\<skill-name>\.
#
# Usage: .\scripts\install.ps1 <skill-name> [target-dir]
#
# Examples:
#   .\scripts\install.ps1 example-skill
#   .\scripts\install.ps1 example-skill C:\Users\me\.claude\skills

param(
    [Parameter(Mandatory=$true)]
    [string]$SkillName,

    [string]$TargetDir = "$env:USERPROFILE\.claude\skills"
)

$RepoRoot  = Split-Path -Parent $PSScriptRoot
$SkillsDir = Join-Path $RepoRoot "plugins\team-skills\skills"
$SkillSrc  = Join-Path $SkillsDir $SkillName

if (-not (Test-Path $SkillSrc)) {
    Write-Error "Skill '$SkillName' not found in $SkillsDir"
    Write-Host "Available skills:"
    Get-ChildItem $SkillsDir -Directory | Select-Object -ExpandProperty Name
    exit 1
}

if (-not (Test-Path (Join-Path $SkillSrc "SKILL.md"))) {
    Write-Error "SKILL.md not found in $SkillSrc — skill is malformed."
    exit 1
}

$Dest = Join-Path $TargetDir $SkillName
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

Copy-Item (Join-Path $SkillSrc "SKILL.md") (Join-Path $Dest "SKILL.md")
$Readme = Join-Path $SkillSrc "README.md"
if (Test-Path $Readme) { Copy-Item $Readme (Join-Path $Dest "README.md") }

Write-Host "Skill '$SkillName' installed to $Dest"
Write-Host "Restart Claude Code to apply. The skill will be available as /$SkillName"
