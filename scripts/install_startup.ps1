# Adds (or with -Remove, removes) a Startup-folder shortcut that runs the organizer at login, without a console.
param([switch]$Remove)

$project = Split-Path -Parent $PSScriptRoot
$shortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'Download Organizer.lnk'

if ($Remove) {
    if (Test-Path $shortcut) { Remove-Item $shortcut -Confirm:$false; "Removed $shortcut" } else { "No shortcut to remove." }
    return
}

$pythonw = Join-Path $project '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "Missing $pythonw. Create the venv first (see README)." }

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($shortcut)
$lnk.TargetPath = $pythonw
$lnk.Arguments = "`"$(Join-Path $project 'run.pyw')`""
$lnk.WorkingDirectory = $project
$lnk.Description = 'Download Organizer'
$lnk.Save()
"Created $shortcut"
