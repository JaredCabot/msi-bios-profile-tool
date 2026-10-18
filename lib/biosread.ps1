# Reads the firmware settings variables listed in -ListFile (lines of Name|GUID) and writes them to
# <OutDir>\uefi-vars.json. Read-only: it uses GetFirmwareEnvironmentVariableExW and loads no driver.
# Needs an administrator PowerShell (SeSystemEnvironmentPrivilege). Started by msibios.py.
param([Parameter(Mandatory=$true)][string]$OutDir, [Parameter(Mandatory=$true)][string]$ListFile)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force $OutDir | Out-Null
$log = Join-Path $OutDir 'read.log'
"start $(Get-Date -f s)" | Out-File $log
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class Fw {
  [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  public static extern uint GetFirmwareEnvironmentVariableExW(string name, string guid, byte[] buf, uint size, out uint attr);
  [DllImport("ntdll.dll")]
  public static extern int RtlAdjustPrivilege(int priv, bool enable, bool thread, out bool was);
}
'@
$was = $false
$st = [Fw]::RtlAdjustPrivilege(22, $true, $false, [ref]$was)
"privilege status $st" | Out-File $log -Append
$rows = @()
foreach ($line in Get-Content $ListFile) {
  if (-not $line.Contains('|')) { continue }
  $n, $g = $line.Trim().Split('|')
  $buf = New-Object byte[] 262144
  $attr = [uint32]0
  $len = [Fw]::GetFirmwareEnvironmentVariableExW($n, '{' + $g + '}', $buf, [uint32]$buf.Length, [ref]$attr)
  $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
  $data = ''
  if ($len -gt 0) { $data = [Convert]::ToBase64String($buf, 0, [int]$len) }
  $rows += [pscustomobject]@{ name = $n; guid = $g; len = [int]$len; attr = [int]$attr; err = $err; data = $data }
  "$n {$g} len=$len attr=0x$('{0:X}' -f $attr) err=$err" | Out-File $log -Append
}
$bios = Get-CimInstance Win32_BIOS
$meta = [pscustomobject]@{ taken = (Get-Date -f s); bios = $bios.SMBIOSBIOSVersion; biosDate = "$($bios.ReleaseDate)"; board = (Get-CimInstance Win32_BaseBoard).Product; computer = $env:COMPUTERNAME }
[pscustomobject]@{ meta = $meta; vars = $rows } | ConvertTo-Json -Depth 4 | Out-File (Join-Path $OutDir 'uefi-vars.json') -Encoding ascii
"done $(Get-Date -f s) read=$(($rows | Where-Object { $_.len -gt 0 }).Count) of $($rows.Count)" | Out-File $log -Append
