$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
$cf = Join-Path $root "cloudflare"
$infoFile = Join-Path $root "서버정보.txt"
Set-Location $cf

function Fail($msg) { Write-Host "`n$msg" -ForegroundColor Red; Read-Host "Enter를 누르면 닫힙니다"; exit 1 }
function Step($msg) { Write-Host "`n$msg" -ForegroundColor Cyan }

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
    Fail "Node.js가 없습니다. https://nodejs.org 에서 LTS 버전을 설치한 뒤 이 파일을 다시 실행하세요."
}

Step "[1/5] 클라우드플레어 로그인 확인"
$who = (npx --yes wrangler whoami 2>&1 | Out-String)
if ($who -match "not authenticated|You are not") {
    Write-Host "브라우저가 열리면 [Allow]를 눌러주세요."
    npx --yes wrangler login
    if ($LASTEXITCODE -ne 0) { Fail "로그인 실패" }
}

Step "[2/5] 데이터베이스(D1) 준비"
function Get-DbId {
    $j = (npx wrangler d1 list --json 2>$null | Out-String)
    try { $list = $j | ConvertFrom-Json } catch { return $null }
    ($list | Where-Object { $_.name -eq "workdiary" } | Select-Object -First 1).uuid
}
$dbId = Get-DbId
if (-not $dbId) {
    npx wrangler d1 create workdiary
    $dbId = Get-DbId
}
if (-not $dbId) { Fail "D1 데이터베이스를 만들지 못했습니다." }
$toml = Join-Path $cf "wrangler.toml"
$t = [IO.File]::ReadAllText($toml)
$t = $t -replace 'database_id = ".*?"', "database_id = `"$dbId`""
[IO.File]::WriteAllText($toml, $t, (New-Object Text.UTF8Encoding $false))
Write-Host "D1: $dbId"

npx wrangler d1 execute workdiary --remote --file=schema.sql --yes
if ($LASTEXITCODE -ne 0) { Fail "테이블 생성 실패" }

Step "[3/5] 서버 배포"
$out = (npx wrangler deploy 2>&1 | Tee-Object -Variable raw | Out-String)
Write-Host $out
if ($LASTEXITCODE -ne 0) { Fail "배포 실패 (위 메시지를 캡처해서 보내주세요)" }
$m = [regex]::Match($out, "https://[a-z0-9-]+\.[a-z0-9-]+\.workers\.dev")
if (-not $m.Success) { Fail "배포 주소(workers.dev)를 찾지 못했습니다. 위 메시지를 캡처해서 보내주세요." }
$url = $m.Value

Step "[4/5] 비밀키 설정"
$key = $null
if (Test-Path $infoFile) {
    $old = Get-Content $infoFile -Encoding UTF8 | Where-Object { $_ -like "WORKER_KEY=*" }
    if ($old) { $key = $old.Substring(11) }
}
if (-not $key) { $key = -join ((1..40) | ForEach-Object { "abcdefghijkmnpqrstuvwxyz23456789"[(Get-Random -Maximum 32)] }) }
$key | npx wrangler secret put APP_KEY
if ($LASTEXITCODE -ne 0) { Fail "비밀키 설정 실패" }

"WORKER_URL=$url`r`nWORKER_KEY=$key" | Set-Content $infoFile -Encoding UTF8

Step "[5/5] 서버 응답 확인"
Start-Sleep -Seconds 3
try {
    $r = Invoke-RestMethod $url -TimeoutSec 20
    if ($r.ok) { Write-Host "서버 정상 작동 ✅" -ForegroundColor Green }
} catch { Write-Host "응답 확인 실패 (몇 분 뒤 정상화될 수 있음): $_" -ForegroundColor Yellow }

Write-Host "`n완료! 서버 주소: $url"
Write-Host "서버정보.txt 에 저장했습니다. 이제 2_깃허브_업로드.bat 을 실행하세요." -ForegroundColor Green
Read-Host "Enter를 누르면 닫힙니다"
