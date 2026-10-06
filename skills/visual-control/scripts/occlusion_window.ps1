# Occlusion experiment: a GREEN target window with a white square, covered by a
# RED window.  Used to check whether a capture method returns the target window's
# own pixels or whatever is physically on screen.
param(
  [Parameter(Mandatory = $true)][ValidateSet('target', 'cover')][string]$Role,
  [string]$Result = "$env:TEMP\vc-occlusion.jsonl",
  [string]$Marker = 'x'
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -Namespace VC -Name Dpi -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][VC.Dpi]::SetProcessDPIAware()

function Ev([string]$k, [string]$v) {
  ([ordered]@{ kind = $k; value = $v }) | ConvertTo-Json -Compress | Add-Content $Result -Encoding utf8
}

$f = New-Object System.Windows.Forms.Form
$f.FormBorderStyle = 'None'
$f.StartPosition = 'Manual'
$f.KeyPreview = $true

if ($Role -eq 'target') {
  $f.Text = 'VCOcclusionTarget'
  $f.BackColor = [System.Drawing.Color]::FromArgb(0, 200, 60)   # green
  $f.Size = New-Object System.Drawing.Size(640, 520)
  $f.Location = New-Object System.Drawing.Point(180, 180)
  # a white square makes the expected content unambiguous
  $box = New-Object System.Windows.Forms.Panel
  $box.BackColor = [System.Drawing.Color]::White
  $box.Location = New-Object System.Drawing.Point(60, 60)
  $box.Size = New-Object System.Drawing.Size(200, 160)
  $f.Controls.Add($box)
} else {
  $f.Text = 'VCOcclusionCover'
  $f.BackColor = [System.Drawing.Color]::FromArgb(220, 30, 30)  # red
  $f.Size = New-Object System.Drawing.Size(640, 520)
  $f.Location = New-Object System.Drawing.Point(260, 260)
}

$f.Add_Shown({
  Ev 'shown' ($f.Handle.ToString() + '|' + $Role + '|' + $Marker)
})
[System.Windows.Forms.Application]::Run($f)
