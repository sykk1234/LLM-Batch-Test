@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==========================================================
echo   第一步：试跑（不看结果，只看流程）
echo   不花钱 / 不用填 key / 不用装任何东西
echo ==========================================================
echo.
echo  会跑 16 条测试题。注意：output 列是【假答案】，
echo  因为我们故意不调用大模型。这一步只为确认流程通不通。
echo.

py -V >nul 2>nul
if errorlevel 1 goto TRY_PYTHON
set PYCMD=py
goto RUN

:TRY_PYTHON
python -V >nul 2>nul
if errorlevel 1 goto NOPY
set PYCMD=python

:RUN
echo  正在跑，大概 2 秒...
echo.
%PYCMD% 02_batch_test.py --input prompts.csv --output results_试跑.csv --dry-run --workers 4
if errorlevel 1 goto FAIL

echo.
echo ==========================================================
echo  流程通了。现在用 Excel 打开结果表给你看。
echo  看完这一列假答案，就可以去准备真跑了。
echo ==========================================================
echo.
pause
start "" results_试跑.csv
exit /b 0

:NOPY
echo  [错误] 没找到 Python。
echo  请先装 Python 3.10 或更高版本：https://www.python.org/downloads/
echo  安装时记得勾选 Add Python to PATH。
pause
exit /b 1

:FAIL
echo.
echo  [错误] 脚本跑失败了，把上面的报错截图发给阿泡。
pause
exit /b 1
