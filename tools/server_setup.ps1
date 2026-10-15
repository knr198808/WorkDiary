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

# 기존 서버정보 읽기 (다시 실행해도 키가 바뀌지 않게)
$info = [ordered]@{}
if (Test-Path $infoFile) {
    Get-Content $infoFile -Encoding UTF8 | ForEach-Object { $k, $v = $_ -split "=", 2; if ($v) { $info[$k.Trim()] = $v.Trim() } }
}

Step "[1/7] 클라우드플레어 로그인 확인"
$who = (npx --yes wrangler whoami 2>&1 | Out-String)
if ($who -match "not authenticated|You are not") {
    Write-Host "브라우저가 열리면 [Allow]를 눌러주세요."
    npx --yes wrangler login
    if ($LASTEXITCODE -ne 0) { Fail "로그인 실패" }
}

Step "[2/7] 데이터베이스(D1) 준비"
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

Step "[3/7] 서버 배포"
$out = (npx wrangler deploy 2>&1 | Tee-Object -Variable raw | Out-String)
Write-Host $out
if ($LASTEXITCODE -ne 0) { Fail "배포 실패 (위 메시지를 캡처해서 보내주세요)" }
$m = [regex]::Match($out, "https://[a-z0-9-]+\.[a-z0-9-]+\.workers\.dev")
if (-not $m.Success) { Fail "배포 주소(workers.dev)를 찾지 못했습니다. 위 메시지를 캡처해서 보내주세요." }
$url = $m.Value

Step "[4/7] 비밀키 설정"
$key = $info["WORKER_KEY"]
if (-not $key) { $key = -join ((1..40) | ForEach-Object { "abcdefghijkmnpqrstuvwxyz23456789"[(Get-Random -Maximum 32)] }) }
$key | npx wrangler secret put APP_KEY
if ($LASTEXITCODE -ne 0) { Fail "비밀키 설정 실패" }
# 라이선스 관리 페이지 비밀번호 (처음 한 번 만들고 계속 같은 값 사용)
$adminPass = $info["ADMIN_PASS"]
if (-not $adminPass) { $adminPass = -join ((1..20) | ForEach-Object { "abcdefghijkmnpqrstuvwxyz23456789"[(Get-Random -Maximum 32)] }) }
$adminPass | npx wrangler secret put ADMIN_PASS
if ($LASTEXITCODE -ne 0) { Fail "관리 비밀번호 설정 실패" }
$info["ADMIN_PASS"] = $adminPass

Step "[5/7] 폰 알림(웹앱 푸시) 키 설정"
if (-not $info["VAPID_PUBLIC"] -or -not $info["VAPID_PRIVATE_JWK"]) {
    $gen = node (Join-Path $PSScriptRoot "vapid_keys.js")
    if ($LASTEXITCODE -ne 0) { Fail "폰 알림 키 생성 실패" }
    foreach ($ln in $gen) { $k, $v = $ln -split "=", 2; $info[$k] = $v }
}
$info["VAPID_PUBLIC"] | npx wrangler secret put VAPID_PUBLIC
if ($LASTEXITCODE -ne 0) { Fail "폰 알림 키 설정 실패" }
$info["VAPID_PRIVATE_JWK"] | npx wrangler secret put VAPID_PRIVATE_JWK
if ($LASTEXITCODE -ne 0) { Fail "폰 알림 키 설정 실패" }

Step "[6/7] 텔레그램 공용 봇 연결 (선택)"
if (-not $info["TG_BOT_TOKEN"]) {
    Write-Host "텔레그램 @BotFather 에서 받은 봇 토큰을 붙여넣고 Enter 하세요. (텔레그램 안 쓰면 그냥 Enter)"
    $tok = Read-Host "봇 토큰"
    if ($tok) { $info["TG_BOT_TOKEN"] = $tok.Trim() }
}
if ($info["TG_BOT_TOKEN"]) {
    $tok = $info["TG_BOT_TOKEN"]
    try { $me = Invoke-RestMethod "https://api.telegram.org/bot$tok/getMe" -TimeoutSec 20 }
    catch { Fail "봇 토큰이 올바르지 않아요. 서버정보.txt 에서 TG_BOT_TOKEN 줄을 지우고 다시 실행하세요." }
    $info["TG_BOT_USERNAME"] = $me.result.username
    if (-not $info["TG_WEBHOOK_SECRET"]) {
        $info["TG_WEBHOOK_SECRET"] = -join ((1..32) | ForEach-Object { "abcdefghijkmnpqrstuvwxyz23456789"[(Get-Random -Maximum 32)] })
    }
    foreach ($k in "TG_BOT_TOKEN", "TG_BOT_USERNAME", "TG_WEBHOOK_SECRET") {
        $info[$k] | npx wrangler secret put $k
        if ($LASTEXITCODE -ne 0) { Fail "텔레그램 설정 실패 ($k)" }
    }
    $hook = @{ url = "$url/tg/hook"; secret_token = $info["TG_WEBHOOK_SECRET"]; allowed_updates = @("message") } | ConvertTo-Json
    $r1 = Invoke-RestMethod -Method Post "https://api.telegram.org/bot$tok/setWebhook" -Body ([Text.Encoding]::UTF8.GetBytes($hook)) -ContentType "application/json; charset=utf-8"
    $cmds = @{ commands = @(@{ command = "list"; description = "예정된 알림 보기" }, @{ command = "stop"; description = "알림 끄기" }) } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Method Post "https://api.telegram.org/bot$tok/setMyCommands" -Body ([Text.Encoding]::UTF8.GetBytes($cmds)) -ContentType "application/json; charset=utf-8" | Out-Null
    if ($r1.ok) { Write-Host "텔레그램 봇 @$($info['TG_BOT_USERNAME']) 연결 완료 ✅" -ForegroundColor Green }
    else { Write-Host "텔레그램 웹훅 설정 실패: $($r1.description)" -ForegroundColor Yellow }
} else {
    Write-Host "텔레그램은 건너뜀 (나중에 이 파일을 다시 실행해서 추가할 수 있어요)"
}

$info["WORKER_URL"] = $url
$info["WORKER_KEY"] = $key
($info.Keys | ForEach-Object { "$_=$($info[$_])" }) -join "`r`n" | Set-Content $infoFile -Encoding UTF8

Step "[7/7] 서버 응답 확인"
Start-Sleep -Seconds 3
try {
    $r = Invoke-RestMethod $url -TimeoutSec 20
    if ($r.ok -and $r.webpush) { Write-Host "서버 정상 작동 ✅  (폰 웹앱 알림 켜짐)" -ForegroundColor Green }
    elseif ($r.ok) { Write-Host "서버는 작동하지만 폰 알림 키가 아직 반영 안 됨 — 1분 뒤 다시 확인해 보세요" -ForegroundColor Yellow }
} catch { Write-Host "응답 확인 실패 (몇 분 뒤 정상화될 수 있음): $_" -ForegroundColor Yellow }

Write-Host "`n완료! 서버 주소: $url"
Write-Host "라이선스 관리 페이지: $url/admin   (비밀번호: $adminPass  → 4_라이선스_관리.bat 으로 열면 자동 복사)" -ForegroundColor Yellow
Write-Host "서버정보.txt 에 저장했습니다." -ForegroundColor Green
if (-not (Test-Path (Join-Path $root ".git"))) { Write-Host "이제 2_깃허브_업로드.bat 을 실행하세요." -ForegroundColor Green }
Read-Host "Enter를 누르면 닫힙니다"
