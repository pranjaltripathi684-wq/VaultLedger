' VaultLedger silent launcher: starts the Flask server with no console window
' and opens the app in the default browser.
Option Explicit

Dim shell, fso, appDir, pythonCmd, http, alreadyRunning, i
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = appDir

' Is the server already running? (avoids "port in use" when launched twice)
alreadyRunning = ServerIsUp()

If Not alreadyRunning Then
    ' Prefer pythonw (no console window); fall back to python, hidden.
    If CommandExists("pythonw") Then
        pythonCmd = "pythonw"
    ElseIf CommandExists("python") Then
        pythonCmd = "python"
    Else
        MsgBox "Python is not installed or not on PATH." & vbCrLf & _
               "Install it from https://python.org and run 'pip install -r requirements.txt'.", _
               vbCritical, "VaultLedger"
        WScript.Quit 1
    End If

    shell.Run pythonCmd & " """ & appDir & "\app.py""", 0, False

    ' Wait up to ~15 seconds for the server to come up
    For i = 1 To 30
        WScript.Sleep 500
        If ServerIsUp() Then Exit For
    Next

    If Not ServerIsUp() Then
        MsgBox "VaultLedger did not start. Run Start-FinanceTracker.bat to see the error " & _
               "(Flask may be missing: pip install -r requirements.txt).", vbExclamation, "VaultLedger"
        WScript.Quit 1
    End If
End If

shell.Run "http://127.0.0.1:5000/"

Function CommandExists(cmd)
    CommandExists = (shell.Run("cmd /c where " & cmd & " >nul 2>&1", 0, True) = 0)
End Function

Function ServerIsUp()
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP")
    http.setTimeouts 500, 500, 500, 500
    http.Open "GET", "http://127.0.0.1:5000/api/dashboard", False
    http.Send
    ServerIsUp = (Err.Number = 0 And http.Status = 200)
    Err.Clear
    On Error GoTo 0
End Function
