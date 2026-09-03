' Runs a PowerShell script with no window at all.
'
'   wscript.exe run_hidden.vbs [script.ps1]
'
' Defaults to update_and_publish.ps1 when no script is named, which is how the
' original scheduled task calls it.
'
' Task Scheduler starting powershell.exe itself draws a console on whichever
' desktop is logged in, so an hourly schedule means an hourly window.
' -WindowStyle Hidden does not help: the console exists before PowerShell reads
' its own arguments, so it still flashes up. Starting it from WScript with a
' window style of 0 means no console is ever created.
'
' Nothing is on screen, so output goes to a log named after the script, next to
' this file. That is the place to look when a run did not do what you expected.

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

here = fso.GetParentFolderName(WScript.ScriptFullName)

If WScript.Arguments.Count > 0 Then
    target = WScript.Arguments(0)
Else
    target = "update_and_publish.ps1"
End If

script = fso.BuildPath(here, target)
If Not fso.FileExists(script) Then
    ' No console to complain to, so leave the reason somewhere findable.
    fso.OpenTextFile(fso.BuildPath(here, "run_hidden_error.log"), 8, True) _
       .WriteLine Now & " no such script: " & script
    WScript.Quit 1
End If

' auto_update.log for update_and_publish.ps1, nudge_publish.log for the nudge.
base = fso.GetBaseName(script)
If base = "update_and_publish" Then
    logf = fso.BuildPath(here, "auto_update.log")
Else
    logf = fso.BuildPath(here, base & ".log")
End If

' Hourly forever would otherwise grow without limit. A megabyte is a few
' hundred runs, far more history than anyone reads.
If fso.FileExists(logf) Then
    If fso.GetFile(logf).Size > 1048576 Then
        fso.CopyFile logf, fso.BuildPath(here, base & ".prev.log"), True
        fso.DeleteFile logf
    End If
End If

cmd = "cmd.exe /c powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ _
      & script & """ >> """ & logf & """ 2>&1"

sh.Run cmd, 0, False
