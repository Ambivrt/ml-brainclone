# larry-save-positions.ps1
# Koer naar alla 4 agent-foenstren aer oeppna och positionerade.
# Faaangar position + storlek och sparar till window-positions.json.
# Anvaender EnumWindows eftersom alla WT-foenstren delar en process.

Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class WinEnum {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll")]
    public static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll")]
    public static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

    public struct RECT { public int Left, Top, Right, Bottom; }

    public static List<Tuple<IntPtr, string>> GetWindowsWithTitle(string classFilter) {
        var result = new List<Tuple<IntPtr, string>>();
        EnumWindows((hWnd, _) => {
            if (!IsWindowVisible(hWnd)) return true;
            var cls = new StringBuilder(256);
            GetClassName(hWnd, cls, 256);
            if (classFilter != null && !cls.ToString().Contains(classFilter)) return true;
            int len = GetWindowTextLength(hWnd);
            if (len == 0) return true;
            var sb = new StringBuilder(len + 1);
            GetWindowText(hWnd, sb, sb.Capacity);
            result.Add(Tuple.Create(hWnd, sb.ToString()));
            return true;
        }, IntPtr.Zero);
        return result;
    }
}
'@

$agents  = @("Larry", "Barry", "Harry", "Parry")
$found   = @{}

# Hiitta alla synliga WT-foenstren (klass: CASCADIA_HOSTING_WINDOW_CLASS)
$windows = [WinEnum]::GetWindowsWithTitle("CASCADIA")

Write-Host "Hittade $($windows.Count) WT-foenstren:"
foreach ($w in $windows) {
    Write-Host "  HWND=$($w.Item1)  Titel='$($w.Item2)'"
}
Write-Host ""

foreach ($w in $windows) {
    $title = $w.Item2
    foreach ($agent in $agents) {
        if ($title -like "*$agent*") {
            $rect = New-Object WinEnum+RECT
            [WinEnum]::GetWindowRect($w.Item1, [ref]$rect) | Out-Null
            $found[$agent] = @{
                X = $rect.Left
                Y = $rect.Top
                W = $rect.Right  - $rect.Left
                H = $rect.Bottom - $rect.Top
            }
            Write-Host "[OK] $agent hittad: X=$($rect.Left) Y=$($rect.Top) W=$($rect.Right - $rect.Left) H=$($rect.Bottom - $rect.Top)" -ForegroundColor Green
        }
    }
}

$missing = $agents | Where-Object { -not $found.ContainsKey($_) }

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "[FEL] Saknar foenstren foer: $($missing -join ', ')" -ForegroundColor Red
    Write-Host "Titlarna ovan matchar inte agent-namnen. Kontrollera att foenstren har ratt titel." -ForegroundColor Yellow
    exit 1
}

$outPath = "$PSScriptRoot\window-positions.json"
$found | ConvertTo-Json -Depth 3 | Set-Content $outPath -Encoding UTF8
Write-Host ""
Write-Host "Positioner sparade till: $outPath" -ForegroundColor Cyan
