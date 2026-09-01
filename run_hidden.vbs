' Launches update_and_publish.ps1 with no window at all.
'
' Task Scheduler used to start powershell.exe itself, which draws a console on
' whichever desktop is logged in: an hourly schedule meant an hourly window.
' -WindowStyle Hidden is not enough on its own, because the console is created
' before PowerShell reads its own arguments and so still flashes up. Starting
' it from WScript with a window style of 0 means no console is ever created.
'
' Nothing is on screen any more, so the output goes to auto_update.log next to
' this file. That is the place to look when a run did not publish.

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

here   = fso.GetParentFolderName(WScript.ScriptFullName)
script = here & "\update_and_publish.ps1"
logf   = here & "\auto_update.log"

' Hourly forever would otherwise grow without limit. A megabyte is a few
' hundred runs, which is far more history than anyone reads.
If fso.FileExists(logf) Then
    If fso.GetFile(logf).Size > 1048576 Then
        fso.CopyFile logf, here & "\auto_update.prev.log", True
        fso.DeleteFile logf
    End If
End If

cmd = "cmd.exe /c powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ _
      & script & """ >> """ & logf & """ 2>&1"

sh.Run cmd, 0, False
