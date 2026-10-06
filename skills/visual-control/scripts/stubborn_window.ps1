# A deliberately STUBBORN window.  Two behaviours, because a capture failure has
# two different shapes and only one of them is distinguishable by pixels:
#
#   -Mode content  blue header + white body drawn in OnPaint.  The window's real
#                  content exists on screen; PrintWindow cannot see it if the app
#                  refuses WM_PRINTCLIENT, so this reproduces "the window has
#                  content, but its own-pixel capture is blank/failing".
#   -Mode white    paints nothing but near-white.  Reproduces an app whose surface
#                  genuinely has no readable content at all.
#
# It also refuses WM_PRINTCLIENT/WM_PRINT, exposing what those messages are worth.
#
# Measured on this host (Windows 11 build 26100): PrintWindow with
# PW_RENDERFULLCONTENT returned the true content even while WM_PRINTCLIENT was
# refused, i.e. it goes through DWM composition and does not depend on the app
# implementing WM_PRINT.  Hence the refresh-failure mode below, which is the one
# that reliably empties the window's own surface: the form stops painting into its
# window after the first frame, so BitBlt of the screen still shows the painted
# pixels while PrintWindow gets a cleared buffer.
param(
  [string]$Result = "$env:TEMP\vc-stubborn.jsonl",
  [int]$TopHeight = 200,
  [ValidateSet('content', 'white')][string]$Mode = 'content',
  [switch]$AllowPrint,
  [switch]$StopPainting
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -Namespace VC -Name Dpi -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][VC.Dpi]::SetProcessDPIAware()

$csharp = @'
using System;
using System.Drawing;
using System.Windows.Forms;

public class StubbornForm : Form
{
    public int TopHeight = 200;
    public Color TopColor = Color.FromArgb(0, 90, 220);
    public Color BottomColor = Color.FromArgb(250, 250, 250);
    public bool RefusePrint = true;
    public bool Blank = false;
    public bool StopPainting = false;
    public int PrintMessages = 0;

    public StubbornForm()
    {
        this.Text = "VCStubborn";
        this.FormBorderStyle = FormBorderStyle.None;
        this.StartPosition = FormStartPosition.Manual;
        this.Location = new Point(220, 220);
        this.Size = new Size(720, 560);
        this.DoubleBuffered = false;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        if (StopPainting && this.PrintMessages > 0)
        {
            // Emulate an app whose surface can no longer be read: stop drawing.
            e.Graphics.Clear(Color.FromArgb(252, 252, 252));
            return;
        }
        e.Graphics.Clear(BottomColor);
        if (!Blank)
        {
            using (SolidBrush brush = new SolidBrush(TopColor))
            {
                e.Graphics.FillRectangle(brush, 0, 0, this.ClientSize.Width, TopHeight);
            }
        }
        base.OnPaint(e);
    }

    protected override void WndProc(ref Message m)
    {
        const int WM_PRINT = 0x0317;
        const int WM_PRINTCLIENT = 0x0318;
        if (m.Msg == WM_PRINT || m.Msg == WM_PRINTCLIENT)
        {
            PrintMessages++;
            if (RefusePrint)
            {
                m.Result = IntPtr.Zero;
                return;
            }
        }
        base.WndProc(ref m);
    }
}
'@
Add-Type -TypeDefinition $csharp -ReferencedAssemblies System.Windows.Forms, System.Drawing

if (Test-Path $Result) { Remove-Item $Result -Force }
function Ev([string]$k, [string]$v) {
  ([ordered]@{ kind = $k; value = $v }) | ConvertTo-Json -Compress | Add-Content $Result -Encoding utf8
}

$form = New-Object StubbornForm
$form.TopHeight = $TopHeight
$form.Blank = ($Mode -eq 'white')
$form.RefusePrint = (-not $AllowPrint)
$form.StopPainting = [bool]$StopPainting
$form.Add_Shown({ Ev 'shown' $form.Handle.ToString(); $form.Refresh() })
[System.Windows.Forms.Application]::Run($form)
