Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName Microsoft.VisualBasic

$interval = [Microsoft.VisualBasic.Interaction]::InputBox(
    "Reminder interval in minutes:",
    "Stand & Relax Reminder",
    "30"
)

if (-not $interval) { exit }

$minutes = [int]$interval

while ($true) {
    Start-Sleep -Seconds ($minutes * 60)

    [System.Windows.MessageBox]::Show(
        "Stand up`n`nRelax your shoulders.`nMove around for a minute.",
        "Movement Reminder"
    )
}
