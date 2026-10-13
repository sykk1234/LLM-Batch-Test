@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==========================================================
echo   生成用例表：把你的原始评论套进提示词模板
echo ==========================================================
echo.
echo  需要两样东西放在本文件夹：
echo    1. 原始数据   comments.txt（一行一条评论）
echo                  或 comments.csv（有表头）
echo    2. 提示词模板  模板A.txt（里面要有一处 {评论}）
echo.
echo  没找到你的数据时，用自带的示例数据演示一遍。
echo.

py -V >nul 2>nul
if errorlevel 1 goto TRY_PYTHON
set PYCMD=py
goto PICK

:TRY_PYTHON
python -V >nul 2>nul
if errorlevel 1 goto NOPY
set PYCMD=python

:PICK
if exist "comments.csv" goto USE_CSV
if exist "comments.txt" goto USE_TXT
set INPUT=comments_示例.txt
echo  （没找到 comments.csv / comments.txt，改用自带的示例数据）
goto GO

:USE_CSV
set INPUT=comments.csv
goto GO

:USE_TXT
set INPUT=comments.txt
goto GO

:GO
if exist "模板B.txt" goto AB
if not exist "模板A.txt" goto NOTPL

echo  模式：单版全量（只有模板A.txt）
echo.
%PYCMD% make_prompts.py --input "%INPUT%" --template-a 模板A.txt --out prompts.csv
if errorlevel 1 goto FAIL
echo.
echo ==========================================================
echo  生成好了。正在用 Excel 打开用例表。
echo  下一步：双击 2-真跑.cmd
echo ==========================================================
echo.
pause
start "" prompts.csv
exit /b 0

:AB
echo  模式：A/B 抽样对照（检测到 模板B.txt，随机抽 30 条 x 2 版）
echo.
echo  说明：先用小样本比出哪版提示词更准，再用单版跑全量，
echo        比 1000 行全量对照省一半的钱。
echo.
%PYCMD% make_prompts.py --input "%INPUT%" --template-a 模板A.txt --template-b 模板B.txt --sample 30 --out prompts_ab.csv
if errorlevel 1 goto FAIL
echo.
echo ==========================================================
echo  生成好了。正在用 Excel 打开对照表。
echo  下一步：把 output 结果按 variant 分组，看 A 和 B 哪个准。
echo ==========================================================
echo.
pause
start "" prompts_ab.csv
exit /b 0

:NOTPL
echo  [还差一步] 没找到 模板A.txt。
echo.
echo  模板就是一个普通的文本文件，里面写提示词，留一处 {评论} 表示评论放在哪。例如：
echo.
echo    判断这条车主评论的情感倾向，只输出：好评/中评/差评/投诉风险
echo    评论内容：{评论}
echo.
echo  本文件夹里已经放好了两个例子（模板A.txt、模板B.txt），直接改它们就行。
pause
exit /b 1

:NOPY
echo  [错误] 没找到 Python。请先安装：https://www.python.org/downloads/
pause
exit /b 1

:FAIL
echo.
echo  [错误] 生成失败了，把上面的报错截图发给阿泡。
pause
exit /b 1
