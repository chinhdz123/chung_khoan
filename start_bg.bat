@echo off
echo Starting ChungKhoanServer in background...
powershell -Command "Start-Process powershell -WindowStyle Hidden -ArgumentList '-ExecutionPolicy Bypass -File \"%~dp0run.ps1\"'"
echo Server is running in the background!
