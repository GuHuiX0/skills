# Probe: can a real window have readable screen pixels while its own-pixel
# (PrintWindow) capture is blank/failing?  That is the case the foreground
# fallback exists for, and it decides how the escalation regression is built.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$vc = Join-Path $root 'visual-control\scripts\visual_control.py'
$stub = Join-Path $root 'visual-control\scripts\stubborn_window.ps1'
$res = Join-Path $env:TEMP 'vc-probe.jsonl'
if (Test-Path $res) { Remove-Item $res -Force }

function Invoke-VC {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  $json = & python $vc @Args 2>&1 | Out-String
  try { return ($json | ConvertFrom-Json) } catch { return [pscustomobject]@{ ok = $false; raw = $json } }
}

$pwshExe = (Get-Process -Id $PID).Path
$proc = Start-Process -FilePath $pwshExe -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-File',$stub,'-Result',$res,'-Mode','content','-StopPainting') -PassThru
Start-Sleep -Seconds 3

$handle = $null
for ($i = 0; $i -lt 20 -and -not $handle; $i++) {
  $line = @(Get-Content $res -Encoding utf8 -ErrorAction SilentlyContinue) | Where-Object { $_ -match 'shown' } | Select-Object -Last 1
  if ($line) { $handle = ($line | ConvertFrom-Json).value } else { Start-Sleep -Milliseconds 250 }
}
if (-not $handle) { Write-Output 'FAILED: stub never appeared'; exit 1 }
Write-Output "stubborn HWND=$handle"

$w = Invoke-VC observe --window $handle --capture window --out (Join-Path $env:TEMP 'vc-probe-window.png')
$s = Invoke-VC observe --window $handle --capture screen --out (Join-Path $env:TEMP 'vc-probe-screen.png')
Write-Output ("window-mode: ok={0} darkest={1} brightest={2} notes={3}" -f $w.ok, $w.capture.pixels.darkest_luma, $w.capture.pixels.brightest_luma, ($w.capture.notes -join ' | '))
Write-Output ("screen-mode: ok={0} darkest={1} brightest={2}" -f $s.ok, $s.capture.pixels.darkest_luma, $s.capture.pixels.brightest_luma)

$diverges = ($s.capture.pixels.darkest_luma -lt 100) -and ($w.capture.pixels.darkest_luma -ge 250)
Write-Output ("DIVERGES (screen has content, own-pixels blank): {0}" -f $diverges)
Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
