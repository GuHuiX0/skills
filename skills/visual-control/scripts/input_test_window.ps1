# Test harness for visual-control input actions.
# Opens a real WinForms window with a TextBox, a checkbox, a button and a
# scrollable panel.  Every interaction appends a JSON line to the result file so
# an agent can verify clicks, typing, hotkeys, scrolling and dragging without
# touching any other application on the desktop.
param(
  [string]$Result = "$env:TEMP\vc-inputtest.jsonl"
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

if (Test-Path $Result) { Remove-Item $Result -Force }
function Write-Event([string]$kind, [string]$value) {
  $obj = [ordered]@{ kind = $kind; value = $value; at = (Get-Date -Format 'HH:mm:ss.fff') }
  ($obj | ConvertTo-Json -Compress) | Add-Content -Path $Result -Encoding utf8
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'VisualControlInputTest'
$form.Size = New-Object System.Drawing.Size(520, 460)
$form.StartPosition = 'Manual'
$form.Location = New-Object System.Drawing.Point(120, 120)
$form.KeyPreview = $true

$text = New-Object System.Windows.Forms.TextBox
$text.Multiline = $true
$text.ScrollBars = 'Vertical'
$text.Location = New-Object System.Drawing.Point(12, 12)
$text.Size = New-Object System.Drawing.Size(480, 160)
$text.Name = 'target'
$text.Add_TextChanged({ Write-Event 'text' $text.Text })
$form.Controls.Add($text)

$check = New-Object System.Windows.Forms.CheckBox
$check.Text = 'ToggleMe'
$check.Location = New-Object System.Drawing.Point(12, 185)
$check.Size = New-Object System.Drawing.Size(200, 24)
$check.Add_CheckedChanged({ Write-Event 'checkbox' $check.Checked.ToString() })
$form.Controls.Add($check)

$button = New-Object System.Windows.Forms.Button
$button.Text = 'PressMe'
$button.Location = New-Object System.Drawing.Point(12, 215)
$button.Size = New-Object System.Drawing.Size(120, 32)
$button.Add_Click({ Write-Event 'button' 'clicked' })
$form.Controls.Add($button)

$scroll = New-Object System.Windows.Forms.Panel
$scroll.Location = New-Object System.Drawing.Point(150, 215)
$scroll.Size = New-Object System.Drawing.Size(342, 120)
$scroll.AutoScroll = $true
$scroll.BackColor = [System.Drawing.Color]::LightSteelBlue
$inner = New-Object System.Windows.Forms.Panel
$inner.Size = New-Object System.Drawing.Size(320, 1200)
$inner.BackColor = [System.Drawing.Color]::Khaki
$scroll.Controls.Add($inner)
$scroll.Add_Scroll({ Write-Event 'scroll' ("{0},{1}" -f $scroll.HorizontalScroll.Value, $scroll.VerticalScroll.Value) })
$form.Controls.Add($scroll)

$menu = New-Object System.Windows.Forms.MenuStrip
$fileMenu = New-Object System.Windows.Forms.ToolStripMenuItem('File')
$saveItem = New-Object System.Windows.Forms.ToolStripMenuItem('Save')
$saveItem.ShortcutKeys = [System.Windows.Forms.Keys]::Control -bor [System.Windows.Forms.Keys]::S
$saveItem.Add_Click({ Write-Event 'hotkey' 'ctrl+s' })
$fileMenu.DropDownItems.Add($saveItem) | Out-Null
$menu.Items.Add($fileMenu) | Out-Null
$form.MainMenuStrip = $menu
$form.Controls.Add($menu)

# KeyPreview + form level handler: every keystroke that reaches the window is
# logged, which makes keyboard verification independent of the focused control.
$form.Add_KeyDown({ Write-Event 'keydown' ($_.KeyCode.ToString() + '|ctrl=' + $_.Control.ToString() + '|shift=' + $_.Shift.ToString()) })
$form.Add_MouseDown({ Write-Event 'mousedown' ("{0},{1}" -f $_.X, $_.Y) })
$form.Add_Shown({ $form.Activate(); $text.Focus(); Write-Event 'shown' $form.Handle.ToString() })

[System.Windows.Forms.Application]::Run($form)
