@echo off
title Create Desktop Shortcut
cd /d "%~dp0"

echo Creating Desktop Shortcut for VaultLedger...
set VBS_SCRIPT=%TEMP%\CreateShortcut.vbs
set TARGET=%CD%\Start-FinanceTracker.vbs

echo Set oWS = WScript.CreateObject("WScript.Shell") > "%VBS_SCRIPT%"
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\VaultLedger.lnk" >> "%VBS_SCRIPT%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS_SCRIPT%"
echo oLink.TargetPath = "%TARGET%" >> "%VBS_SCRIPT%"
echo oLink.WorkingDirectory = "%CD%" >> "%VBS_SCRIPT%"
echo oLink.Description = "Launch VaultLedger App" >> "%VBS_SCRIPT%"
echo oLink.Save >> "%VBS_SCRIPT%"

cscript //nologo "%VBS_SCRIPT%"
del "%VBS_SCRIPT%"

echo.
echo [SUCCESS] "VaultLedger.lnk" shortcut created on your Desktop!
pause
