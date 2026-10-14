<#
새 PC 준비 — 기업추적(뷰어 · 수집)과 Tech(차트 발굴)를 이 PC 에서 돌릴 수 있게 한다.
안내: docs/새PC_설치.md

  powershell -ExecutionPolicy Bypass -File .\새PC_설치.ps1 -CheckOnly   # 무엇이 있고 없는지만 본다(설치 · 등록 안 함)
  powershell -ExecutionPolicy Bypass -File .\새PC_설치.ps1              # 파이썬 패키지 · Tech 가상환경 설치 + 점검
  powershell -ExecutionPolicy Bypass -File .\새PC_설치.ps1 -Schedule    # + 예약 작업 3개 등록(이 PC 에서 자동으로 돌릴 때만)

비밀값(.env · KIS 키)은 값을 읽어 화면에 내지 않는다 — 키 이름과 '있다/없다'만 적는다.
두 PC 가 같은 구글 드라이브 폴더로 동시에 자동 작업(뷰어 · 수집)을 돌리면 캐시가 서로 덮이고 DART 하루 한도를 같이 쓴다 — 한 PC 에서만 -Schedule.
#>
param([switch]$CheckOnly, [switch]$Schedule)
$ErrorActionPreference = 'Stop'
$Base = $PSScriptRoot
$Tech = [IO.Path]::GetFullPath((Join-Path $Base '..\..\Tech'))
$Ok = New-Object System.Collections.Generic.List[string]
$Todo = New-Object System.Collections.Generic.List[string]
function Mark([bool]$good, [string]$msg) { if ($good) { $script:Ok.Add($msg) } else { $script:Todo.Add($msg) } }

function Find-Python([string[]]$tags) {
    # py 실행기(python.org 설치에 같이 옴)로 버전 · 비트를 골라 실제 python.exe 경로를 돌려준다
    foreach ($t in $tags) {
        try {
            $exe = & py $t -c "import sys;print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe)) { return $exe.Trim() }
        } catch { }
    }
    return $null
}

Write-Host "기업추적 폴더: $Base"
Write-Host "Tech 폴더:     $Tech"
Write-Host ""

# ---------------------------------------------------------------- 1) 기업추적 파이썬 (표준 라이브러리 + requests · openpyxl · telethon)
$PyG = Find-Python @('-3.11-32', '-3.11', '-3.12', '-3.13', '-3')
if (-not $PyG) {
    $cand = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311-32\python.exe'
    if (Test-Path $cand) { $PyG = $cand }
}
if ($PyG) {
    $PywG = Join-Path (Split-Path $PyG) 'pythonw.exe'
    Mark (Test-Path $PywG) "기업추적 파이썬: $PyG"
    if (-not $CheckOnly) {
        & $PyG -m pip install --user --upgrade --quiet requests openpyxl telethon
        Mark ($LASTEXITCODE -eq 0) "pip 설치(requests · openpyxl · telethon)"
    } else {
        $miss = & $PyG -c "import importlib.util as u;print(' '.join(m for m in ('requests','openpyxl','telethon') if not u.find_spec(m)))"
        Mark (-not $miss) ("파이썬 패키지" + $(if ($miss) { " 없음: $miss" } else { " 있음" }))
    }
} else {
    $PywG = $null
    Mark $false "파이썬이 없다 — python.org 에서 Python 3.11 이상 설치('py launcher' 포함 체크). 32비트 · 64비트 모두 된다(64비트가 메모리에 낫다)"
}

# ---------------------------------------------------------------- 2) Tech 가상환경 (64비트 · pandas 2.x)
$Venv = Join-Path $env:USERPROFILE '.venvs\chart_screener'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
$Py64 = Find-Python @('-3.13-64', '-3.12-64', '-3.11-64', '-3.13', '-3.12')
if ($Py64) {
    $bits = & $Py64 -c "import struct;print(struct.calcsize('P')*8)"
    if ($bits -ne '64') { $Py64 = $null }
}
if (-not (Test-Path (Join-Path $Tech 'requirements.txt'))) {
    Mark $false "Tech 폴더가 없다 — $Tech (구글 드라이브 동기화를 기다리거나 git clone https://github.com/lkh0797-lab/Tech.git)"
} elseif (Test-Path $VenvPy) {
    if (-not $CheckOnly) { & $VenvPy -m pip install --quiet -r (Join-Path $Tech 'requirements.txt'); Mark ($LASTEXITCODE -eq 0) "Tech 가상환경 패키지 갱신: $Venv" }
    else { Mark $true "Tech 가상환경 있음: $Venv" }
} elseif ($Py64) {
    if (-not $CheckOnly) {
        & $Py64 -m venv $Venv
        & $VenvPy -m pip install --quiet --upgrade pip
        & $VenvPy -m pip install --quiet -r (Join-Path $Tech 'requirements.txt')
        Mark ($LASTEXITCODE -eq 0) "Tech 가상환경 만듦: $Venv (기반 $Py64)"
    } else { Mark $false "Tech 가상환경 없음 — 이 스크립트를 -CheckOnly 없이 돌리면 만든다(기반 $Py64)" }
} else {
    Mark $false "64비트 Python 3.11~3.13 이 없다 — Tech(pandas 2.x)와 일부 검증 도구(py -3.13)에 필요. python.org 또는 Microsoft Store 'Python 3.13'"
}
if (-not (Find-Python @('-3.13'))) { $Todo.Add("참고: 서버의 일부 백테스트 단추는 'py -3.13' 을 부른다(ORBIT_BT_PY 로 바꿀 수 있음) — 없으면 그 단추만 안 된다") }

# ---------------------------------------------------------------- 3) 자료 · 설정 (구글 드라이브로 오는 것)
Mark (Test-Path (Join-Path $Base '종목.txt')) "종목.txt"
$col = Join-Path $Base '기업추적_수집'
Mark (Test-Path $col) "수집 원문 폴더 기업추적_수집 (git 에 없음 — 드라이브 동기화 또는 수집기로 다시 채움)"
$px = Join-Path $Base '.cache\price'
$npx = 0; if (Test-Path $px) { $npx = (Get-ChildItem $px -Filter *.json -File -ErrorAction SilentlyContinue | Measure-Object).Count }
Mark ($npx -gt 100) ".cache (주가 캐시 $npx 곳) — git 에 없음, 드라이브 동기화로 온다. 비어 있으면 처음 계산이 오래 걸린다"

function Read-Keys([string]$path) {
    # 값은 돌려주지 않는다 — 값이 비지 않은 키 이름만
    $names = @()
    if (Test-Path $path) {
        foreach ($line in [IO.File]::ReadAllLines($path)) {
            $l = $line.Trim()
            if ($l -and -not $l.StartsWith('#') -and $l.Contains('=')) {
                $k = $l.Substring(0, $l.IndexOf('=')).Trim(); $v = $l.Substring($l.IndexOf('=') + 1).Trim()
                if ($v) { $names += $k }
            }
        }
    }
    return $names
}
$cfg = @{}
$cfgPath = Join-Path $Base '경로설정.txt'
if (Test-Path $cfgPath) {
    foreach ($line in [IO.File]::ReadAllLines($cfgPath)) {
        $l = $line.Trim()
        if ($l -and -not $l.StartsWith('#') -and $l.Contains('=')) { $cfg[$l.Substring(0, $l.IndexOf('=')).Trim()] = $l.Substring($l.IndexOf('=') + 1).Trim() }
    }
}
$keys = @(Read-Keys (Join-Path $Base '.env'))
if ($cfg['DART_ENV_PATH']) {
    $dp = $cfg['DART_ENV_PATH']
    Mark (Test-Path $dp) "경로설정.txt DART_ENV_PATH → $dp"
    if (Test-Path $dp) { $keys += @(Read-Keys $dp) }
}
if ($cfg['UNIVERSE_XLSX']) {
    $ux = $cfg['UNIVERSE_XLSX']
    Mark ([bool](Get-ChildItem -Path $ux -ErrorAction SilentlyContinue)) "경로설정.txt UNIVERSE_XLSX → $ux"
}
if (-not $Base.StartsWith('G:\내 드라이브')) {
    $Todo.Add("이 PC 의 구글 드라이브 경로가 'G:\내 드라이브' 가 아니다 — 경로설정.txt 의 DART_ENV_PATH · UNIVERSE_XLSX 를 이 PC 경로로 고친다")
}
foreach ($k in @('DART_API_KEY', 'DATA_GO_KR_KEY', 'ECOS_API_KEY', 'KOSIS_API_KEY')) {
    $has = ($keys -contains $k) -or [bool][Environment]::GetEnvironmentVariable($k)
    Mark $has "키 $k"
}
$tg = ($keys -contains 'TELEGRAM_API_ID') -and ($keys -contains 'TELEGRAM_API_HASH')
if ($tg) { $Ok.Add("키 TELEGRAM_API_ID · HASH") } else { $Todo.Add("참고: 텔레그램 키 없음 — 리포트 탭 수집만 안 된다") }

# ---------------------------------------------------------------- 4) 드라이브 밖에 두는 비밀 (직접 옮긴다)
$kis = Join-Path $env:USERPROFILE 'KIS\config\kis_devlp.yaml'
Mark (Test-Path $kis) "KIS 설정 $kis — 없으면 옛 PC 의 같은 파일을 USB 등으로 직접 복사(드라이브 · git · 메신저로 보내지 말 것). 없으면 차트 발굴은 네이버 시세만으로 돈다"
$tgs = Join-Path $env:LOCALAPPDATA '기업추적\telegram.session'
if (Test-Path $tgs) { $Ok.Add("텔레그램 로그인 세션") } else { $Todo.Add("참고: 텔레그램 로그인이 필요하면 터미널에서 python 도구\텔레그램_로그인.py (전화번호 · 코드는 직접 입력)") }

# ---------------------------------------------------------------- 5) 예약 작업 (-Schedule)
if ($Schedule -and -not $CheckOnly) {
    if (-not $PywG) { throw "pythonw.exe 를 못 찾아 예약 작업을 만들 수 없다" }
    Write-Host ""
    Write-Host "주의: 다른 PC 에도 같은 예약 작업이 켜져 있으면 끈다 — 그 PC 에서: Disable-ScheduledTask GiupChujeok_Viewer; Disable-ScheduledTask GiupChujeok_Collect" -ForegroundColor Yellow
    $me = "$env:USERDOMAIN\$env:USERNAME"
    $pr = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
    $st = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    $stA = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew
    $aV = New-ScheduledTaskAction -Execute $PywG -Argument ('"' + (Join-Path $Base 'viewer.py') + '" --no-browser') -WorkingDirectory $Base
    $aC = New-ScheduledTaskAction -Execute $PywG -Argument ('"' + (Join-Path $Base 'run.py') + '" --years 15 --max-calls 17000') -WorkingDirectory $Base
    $aA = New-ScheduledTaskAction -Execute $PywG -Argument ('"' + (Join-Path $Base '점검_매트릭스.py') + '" --all --resume') -WorkingDirectory $Base
    $tLogon = New-ScheduledTaskTrigger -AtLogOn -User $me
    $tLogon.Delay = 'PT1M'
    Register-ScheduledTask -TaskName GiupChujeok_Viewer -Action $aV -Trigger @((New-ScheduledTaskTrigger -Daily -At '00:05'), $tLogon) -Principal $pr -Settings $st -Force | Out-Null
    Register-ScheduledTask -TaskName GiupChujeok_Collect -Action $aC -Trigger (New-ScheduledTaskTrigger -Daily -At '00:10') -Principal $pr -Settings $st -Force | Out-Null
    Register-ScheduledTask -TaskName GiupChujeok_Audit -Action $aA -Principal $pr -Settings $stA -Force | Out-Null
    $Ok.Add("예약 작업 등록: GiupChujeok_Viewer(매일 00:05 + 로그인 1분 뒤) · GiupChujeok_Collect(매일 00:10) · GiupChujeok_Audit(손으로)")
    Start-ScheduledTask -TaskName GiupChujeok_Viewer
    $Ok.Add("뷰어 시작 — 잠시 뒤 http://127.0.0.1:8765 (차트 발굴 자동 스캔은 뷰어가 평일 20:15 에 띄운다)")
}

# ---------------------------------------------------------------- 결과
Write-Host ""
Write-Host "== 됨" -ForegroundColor Green
$Ok | ForEach-Object { Write-Host "  + $_" }
Write-Host "== 할 일 · 참고" -ForegroundColor Yellow
if ($Todo.Count -eq 0) { Write-Host "  (없음)" } else { $Todo | ForEach-Object { Write-Host "  - $_" } }
if (-not $Schedule) { Write-Host ""; Write-Host "이 PC 에서 자동 작업(뷰어 · 밤 수집)을 돌리려면 -Schedule 을 붙여 다시 실행. 손으로만 쓸 거면 기업추적_뷰어.bat 더블클릭." }
