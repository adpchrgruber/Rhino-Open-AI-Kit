@echo off
rem Rhino Open AI Kit - one-time setup for Windows
rem Picks a preset, downloads the llama.cpp runtime and the model, verifies checksums.
rem Runs tools\setup-win.ps1 (only that script, policy unchanged for the rest of the system).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup-win.ps1" %*
pause
