$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
$infoFile = Join-Path $root "서버정보.txt"
Set-Location $root

function Fail($msg) { Write-Host "`n$msg" -ForegroundColor Red; Read-Host "Enter를 누르면 닫힙니다"; exit 1 }
function Step($msg) { Write-Host "`n$msg" -ForegroundColor Cyan }
function Run { & $args[0] $args[1..($args.Count - 1)]; if ($LASTEXITCODE -ne 0) { Fail "실패: $($args -join ' ')" } }

Step "[1/6] Git / GitHub CLI 확인"
$missing = @()
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { $missing += "Git.Git" }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { $missing += "GitHub.cli" }
if ($missing) {
    foreach ($id in $missing) { winget install --id $id -e --accept-source-agreements --accept-package-agreements }
    Fail "설치를 마쳤습니다. 이 창을 닫고 2_깃허브_업로드.bat 을 다시 실행하세요."
}

Step "[2/6] GitHub 로그인 확인"
gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "화면에 나오는 코드를 복사 → 브라우저에서 붙여넣고 승인하세요."
    gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) { Fail "GitHub 로그인 실패" }
}
gh auth setup-git | Out-Null
$login = (gh api user --jq .login).Trim()
$uid = (gh api user --jq .id).Trim()

if (-not (Test-Path $infoFile)) { Fail "서버정보.txt 가 없습니다. 먼저 1_서버배포.bat 을 실행하세요." }
$info = @{}
Get-Content $infoFile -Encoding UTF8 | ForEach-Object { $k, $v = $_ -split "=", 2; if ($v) { $info[$k] = $v.Trim() } }

Step "[3/6] 파일 정리"
$wf = Join-Path $root ".github\workflows"
New-Item -ItemType Directory -Force $wf | Out-Null
if (Test-Path (Join-Path $root "release.yml")) {
    Move-Item -Force (Join-Path $root "release.yml") (Join-Path $wf "release.yml")
}

Step "[4/6] 저장소 만들기"
if (-not (Test-Path (Join-Path $root ".git"))) { Run git init -b main }
if (-not (git config user.name)) { git config user.name $login }
if (-not (git config user.email)) { git config user.email "$uid+$login@users.noreply.github.com" }
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { Run git commit -m "업무 다이어리 첫 업로드" }

$repo = "$login/WorkDiary"
gh repo view $repo 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Run gh repo create WorkDiary --public --description "업무 다이어리" --source . --remote origin
} elseif (-not (git remote 2>$null | Select-String origin)) {
    Run git remote add origin "https://github.com/$repo.git"
}
Run git push -u origin main

Step "[5/6] 서버 정보 등록 (Secrets)"
Run gh secret set WORKER_URL --repo $repo --body $info["WORKER_URL"]
Run gh secret set WORKER_KEY --repo $repo --body $info["WORKER_KEY"]

Step "[6/6] 첫 버전(v1.0.0) 빌드 시작"
git rev-parse v1.0.0 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Run git tag v1.0.0 }
Run git push origin v1.0.0

Write-Host "`n완료! 약 3~5분 뒤 아래 주소에 WorkDiary.exe 가 올라옵니다." -ForegroundColor Green
Write-Host "  빌드 진행: https://github.com/$repo/actions"
Write-Host "  다운로드 : https://github.com/$repo/releases/latest"
Start-Process "https://github.com/$repo/actions"
Read-Host "Enter를 누르면 닫힙니다"
