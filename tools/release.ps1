$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Fail($msg) { Write-Host "`n$msg" -ForegroundColor Red; Read-Host "Enter를 누르면 닫힙니다"; exit 1 }

if (-not (Test-Path ".git")) { Fail "먼저 2_깃허브_업로드.bat 을 실행하세요." }

$last = (git describe --tags --abbrev=0 2>$null)
if (-not $last) { $last = "v1.0.0" }
$n = [regex]::Matches($last, "\d+") | ForEach-Object { [int]$_.Value }
$next = "v$($n[0]).$($n[1]).$($n[2] + 1)"

Write-Host "현재 버전: $last"
$ver = Read-Host "새 버전 (그냥 Enter = $next)"
if (-not $ver) { $ver = $next }
if ($ver -notmatch "^v") { $ver = "v$ver" }
$msg = Read-Host "변경 내용 한 줄 (사용자 업데이트 창에 표시)"
if (-not $msg) { $msg = "$ver 업데이트" }

git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { git commit -m $msg; if ($LASTEXITCODE -ne 0) { Fail "커밋 실패" } }
git tag -a $ver -m $msg
if ($LASTEXITCODE -ne 0) { Fail "이미 있는 버전입니다: $ver" }
git push origin main
git push origin $ver
if ($LASTEXITCODE -ne 0) { Fail "업로드 실패" }

$repo = (gh repo view --json nameWithOwner --jq .nameWithOwner).Trim()
Write-Host "`n$ver 배포 시작! 3~5분 뒤 사용자 프로그램에 업데이트 알림이 뜹니다." -ForegroundColor Green
Start-Process "https://github.com/$repo/actions"
Read-Host "Enter를 누르면 닫힙니다"
