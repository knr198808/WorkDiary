$root = Split-Path $PSScriptRoot -Parent
$infoFile = Join-Path $root "서버정보.txt"
if (-not (Test-Path $infoFile)) { Write-Host "서버정보.txt 가 없어요. 먼저 1_서버배포.bat 을 실행하세요." -ForegroundColor Red; Read-Host "Enter를 누르면 닫힙니다"; exit 1 }
$info = @{}
Get-Content $infoFile -Encoding UTF8 | ForEach-Object { $k, $v = $_ -split "=", 2; if ($v) { $info[$k.Trim()] = $v.Trim() } }
if (-not $info["ADMIN_PASS"]) { Write-Host "관리 비밀번호가 아직 없어요. 1_서버배포.bat 을 한 번 더 실행하세요." -ForegroundColor Red; Read-Host "Enter를 누르면 닫힙니다"; exit 1 }
Set-Clipboard -Value $info["ADMIN_PASS"]
Start-Process ($info["WORKER_URL"].TrimEnd("/") + "/admin")
Write-Host "관리 페이지를 열었어요. 비밀번호는 복사돼 있으니 Ctrl+V 로 붙여넣으세요." -ForegroundColor Green
Start-Sleep -Seconds 3
