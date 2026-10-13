# -*- coding: utf-8 -*-
"""
01 · 最小闭环 —— 调通一次 API，不到 50 行。

目标就一个：亲眼看见「我发一段话 → 模型回一段话 → 我知道花了多少 token」。
看懂这个文件，你就理解了所有大模型 API 的形状；后面所有复杂的东西都只是它的外扩。

准备（各做一次）：
    1. 把 .env.example 复制成 .env，填上你的 key
    2. 双击一次 2-真跑.cmd（它会自动建好环境和装库，之后就不用再管）

运行：
    .venv\\Scripts\\python.exe 01_hello_api.py
"""

import os
import sys


def load_env_file(path):
    """极简 .env 解析器，零依赖。格式：每行一条 KEY=VALUE，忽略空行和 # 注释。"""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

try:
    from openai import OpenAI
except ImportError:
    sys.exit(
        "还没装 openai 库。两个办法二选一：\n"
        "  省事：双击一次 2-真跑.cmd，它会自动装好\n"
        "  手动：.venv\\Scripts\\python.exe -m pip install openai"
    )

# 这三行就是全部「接入信息」。换模型只改 .env，代码一个字都不用动 ——
# 这就是为什么学一套 OpenAI SDK 能通吃智谱 / 千帆 / DeepSeek。
client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),  # 智谱=https://open.bigmodel.cn/api/paas/v4
)

resp = client.chat.completions.create(
    model=os.getenv("LLM_MODEL"),
    # messages 是个列表，按顺序就是对话历史。system 定人设，user 提要求。
    messages=[
        {"role": "system", "content": "你是东风奕派 APP 的产品助理，回答不超过两句话。"},
        {"role": "user", "content": "用车主能听懂的话解释一下什么是 OBD。"},
    ],
    temperature=0.3,  # 0 最稳定、1 最发散。批量测试里通常压到 0~0.3
)

print(resp.choices[0].message.content)
print("-" * 40)
print("本次消耗 token：", resp.usage.total_tokens)
