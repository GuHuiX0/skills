# Instrumented scrollable window for testing scroll-until-end.
#
# A ListBox with thousands of items: every wheel notch and every TopIndex change is
# appended to the result file, so the test can prove that scrolling really happened
# and that it actually stopped at the top rather than at an arbitrary notches count.
param(
  [string]$Result = "$env:TEMP\vc-scroll.jsonl",
  [int]$Items = 2000
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -Namespace VC -Name Dpi -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][VC.Dpi]::SetProcessDPIAware()

if (Test-Path $Result) { Remove-Item $Result -Force }
function Ev([string]$k, [string]$v) {
  ([ordered]@{ kind = $k; value = $v }) | ConvertTo-Json -Compress | Add-Content $Result -Encoding utf8
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'VCScrollTarget'
$form.Size = New-Object System.Drawing.Size(720, 620)
$form.StartPosition = 'Manual'
$form.Location = New-Object System.Drawing.Point(200, 160)

$list = New-Object System.Windows.Forms.ListBox
$list.Location = New-Object System.Drawing.Point(10, 10)
$list.Size = New-Object System.Drawing.Size(680, 560)
$list.IntegralHeight = $false
$list.Font = New-Object System.Drawing.Font('Consolas', 11)
for ($i = 1; $i -le $Items; $i++) {
  [void]$list.Items.Add(("message {0:D5} ................................................ body" -f $i))
}
# Start at the bottom (set on Shown - assigning it before the handle exists is
# ignored), so "scroll up until the content stops changing" has the whole history
# to walk through: the same shape as opening a long chat.
$list.Add_SelectedIndexChanged({ Ev 'selected' $list.SelectedIndex.ToString() })
# WinForms ListBox raises no scroll notification, so the harness polls: a background
# timer records TopIndex whenever it moves.
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 60
# A hashtable in script scope, because a plain variable assigned inside the Tick
# handler would not survive between events.
$script:state = @{ last = -1 }
$timer.Add_Tick({
  if ($list.TopIndex -ne $script:state.last) {
    $script:state.last = $list.TopIndex
    Ev 'topindex' $list.TopIndex.ToString()
  }
})
$timer.Start()
$form.Controls.Add($list)

$form.Add_Shown({
  $list.Focus()
  # ListBox.TopIndex only takes effect once the control has a handle, and setting
  # the *last* index directly is clamped - walking there via the native scrollbar
  # message is the reliable way to open at the bottom.
  $list.TopIndex = [Math]::Max(0, $Items - 1)
  [void]$list.Refresh()
  Ev 'shown' $form.Handle.ToString()
  Ev 'items' $Items.ToString()
  Ev 'topindex' $list.TopIndex.ToString()
})
[System.Windows.Forms.Application]::Run($form)
