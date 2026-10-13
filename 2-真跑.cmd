@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==========================================================
echo   第二步：真跑（output 列才是模型真写的答案）
echo ==========================================================
echo.

if not exist ".env" goto NOENV

if exist ".venv\Scripts\python.exe" goto RUN

echo  第一次真跑，需要准备运行环境。只做这一次，约 30 秒...
echo  （会在本文件夹里建一个 .venv，不污染你系统的 Python）
echo.

py -V >nul 2>nul
if errorlevel 1 goto TRY_PYTHON
set PYCMD=py
goto MAKEVENV

:TRY_PYTHON
python -V >nul 2>nul
if errorlevel 1 goto NOPY
set PYCMD=python

:MAKEVENV
%PYCMD% -m venv .venv
if errorlevel 1 goto VENVFAIL
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --quiet openai
if errorlevel 1 goto VENVFAIL
echo.
echo  环境准备好了。
echo.

:RUN
echo  开始真跑 16 条...
echo.
.venv\Scripts\python.exe 02_batch_test.py --input prompts.csv --output results.csv
if errorlevel 1 goto FAIL

echo.
echo ==========================================================
echo  跑完了。正在用 Excel 打开真实结果。
echo ==========================================================
echo.
pause
start "" results.csv
exit /b 0

:NOENV
echo  [还差一步] 没找到 .env 配置文件。
echo.
echo  请这样做（3 分钟）：
echo    1. 到 https://open.bigmodel.cn 用手机号注册（免费）
echo    2. 在左侧菜单找「API Keys」，新建一个，复制那串 key
echo       （必须含一个点号，形如 xxxxxxxx.xxxxxxxx。没有点号说明复制的是 ID）
echo    3. 回到本文件夹，用记事本打开  .env（模板已经写在里面了）
echo    4. 把 LLM_API_KEY 那一行等号后面换成你的 key，保存
echo    5. 重新双击本文件
echo.
pause
exit /b 1

:NOPY
echo  [错误] 没找到 Python，请先安装：https://www.python.org/downloads/
pause
exit /b 1

:VENVFAIL
echo.
echo  [错误] 准备运行环境失败（通常是网络问题）。
echo  把上面的报错截图发给阿泡。
pause
exit /b 1

:FAIL
echo.
echo  [错误] 跑失败了。常见原因：
echo    - key 填错，或等号后面多了空格 / 少了字符
echo    - key 和 base_url 不是同一家的
echo    - 免费额度用完了
echo  把上面的报错截图发给阿泡。
pause
exit /b 1
