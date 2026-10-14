@echo off
rem GitHub App entry for git (issue #513). Details live in yudao_github_app.py.
rem Effective when this directory is first on PATH; without the two environment
rem variables the behaviour of the original git is unchanged.
rem This file only locates the real git and hands over to the Python module.
setlocal enabledelayedexpansion
set SELF=%~dp0
set REAL=
for /f "delims=" %%i in ('where git 2^>nul') do (
  if not "%%~dpi"=="!SELF!" (set REAL=%%i & goto :found)
)
:found
if not defined REAL (
  echo yudao github-app: git not found on PATH 1>&2
  exit /b 127
)
if defined YUDAO_GH_APP_ID goto configured
if defined YUDAO_GH_APP_KEY_FILE goto configured
"%REAL%" %*
exit /b %ERRORLEVEL%
:configured
python "%~dp0yudao_github_app.py" git "%REAL%" %*
exit /b %ERRORLEVEL%
