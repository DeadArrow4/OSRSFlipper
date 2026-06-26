# Run from C:\OSRSFlipper

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "OSRSFlipper GitHub Repository Setup" -ForegroundColor Cyan
Write-Host ""

if (!(Test-Path ".gitignore")) {
    Write-Host "Missing .gitignore. Copy the provided .gitignore into C:\OSRSFlipper first." -ForegroundColor Yellow
    exit 1
}

Write-Host "Checking Git..."
git --version

Write-Host ""
Write-Host "Initializing repository..."
git init

Write-Host ""
Write-Host "Checking ignored private files..."
git status --ignored --short

Write-Host ""
Write-Host "Staging safe source files..."
git add .

Write-Host ""
Write-Host "Review staged files carefully. Private files must NOT appear below:"
git diff --cached --name-only

Write-Host ""
Write-Host "Pausing before commit."
Read-Host "Press Enter only if staged files look safe"

git commit -m "Release OSRSFlipper 1.0.0"

Write-Host ""
Write-Host "Next create the GitHub repository."
Write-Host "Recommended private repo command:"
Write-Host "gh repo create OSRSFlipper --private --source=. --remote=origin --push" -ForegroundColor Green
Write-Host ""
