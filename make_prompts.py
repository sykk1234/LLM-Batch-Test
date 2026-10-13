# -*- coding: utf-8 -*-
"""
make_prompts.py —— 把原始数据套进提示词模板，生成 02_batch_test.py 能直接吃的 prompts.csv

解决的问题
----------
500 条车主评论要打标签，手工把评论一条条贴进 prompt 列不现实。
这个脚本自动拼，并且顺手处理三件事：

  1. 编码兼容 —— UTF-8 / GBK 都自动试（Excel 导出的 CSV 常是 GBK）
  2. CSV 转义 —— 评论里的逗号、引号、换行不会撑破表格
  3. 模板校验 —— 模板里没写占位符就立刻报错，
     否则 500 行 prompt 会完全一样，跑出 500 个同样结果，钱白花

两种模式
--------
全量单版：500 条 → 500 行，variant 留空
    python make_prompts.py --input comments.txt --template-a 模板A.txt --out prompts.csv

抽样 A/B：随机抽 K 条，套两个模板 → 2K 行，用来选哪版提示词更准
    python make_prompts.py --input comments.txt --template-a 模板A.txt --template-b 模板B.txt \
        --sample 30 --out prompts_ab.csv

模板怎么写
----------
模板文件里留一处 {评论}，脚本把它换成每一条原始数据：

    判断下面这条车主评论的情感倾向，只输出：好评/中评/差评/投诉风险
    评论内容：{评论}

占位符用普通字符串替换实现（不是 str.format），
所以模板里写 JSON 的花括号 {} 完全不受影响。
"""

import argparse
import csv
import os
import random
import shutil
import sys

PLACEHOLDER = "{评论}"
OUT_FIELDS = ["id", "variant", "prompt"]


def read_text(path):
    """读文本文件，返回全文。UTF-8 / GBK 都试一遍。"""
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    sys.exit(
        f"读不了 {path}：编码既不是 UTF-8 也不是 GBK。\n"
        f"  用记事本打开 → 另存为 → 右下角「编码」选 UTF-8，再试。"
    )


def read_txt_items(path):
    """一行一条。返回 [(序号, 文本), ...]，跳过空行。"""
    items, seq = [], 0
    for line in read_text(path).splitlines():
        text = line.strip()
        if text:
            seq += 1
            items.append((seq, text))
    return items


def read_csv_items(path, text_col):
    """从 CSV 取一列。返回 ([(序号, 文本), ...], 实际用的列名)。"""
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            break
        except UnicodeDecodeError:
            continue
    else:
        sys.exit(f"读不了 {path}：编码既不是 UTF-8 也不是 GBK。")

    if not rows:
        sys.exit(f"{path} 里没有数据行。")

    columns = list(rows[0].keys())
    if text_col:
        if text_col not in columns:
            sys.exit(
                f"{path} 里没有列「{text_col}」。\n"
                f"  现有列：{' / '.join(columns)}\n"
                f"  用 --text-col 指定正确列名（注意空格和大小写）。"
            )
        col = text_col
    else:
        col = columns[0]

    items, seq = [], 0
    for r in rows:
        text = str(r.get(col) or "").strip()
        if text:
            seq += 1
            items.append((seq, text))
    return items, col


def read_template(path):
    """读模板并校验占位符。校验这一步是省钱的关键。"""
    tpl = read_text(path).strip()
    if PLACEHOLDER not in tpl:
        sys.exit(
            f"\n模板 {path} 里没有占位符 {PLACEHOLDER}。\n"
            f"  模板必须留一处 {PLACEHOLDER}，脚本才知道把每条评论插在哪。\n"
            f"  现在这样，所有行的 prompt 会一模一样，跑出来是一堆重复结果，钱就白花了。\n"
            f"  例：\n"
            f"      判断这条车主评论的情感倾向，只输出：好评/中评/差评/投诉风险\n"
            f"      评论内容：{PLACEHOLDER}\n"
        )
    return tpl


def build(items, template, variant):
    """把 (序号, 文本) 列表套进模板，返回结果行。"""
    return [
        {"id": i, "variant": variant, "prompt": template.replace(PLACEHOLDER, t)}
        for i, t in items
    ]


def write_rows(path, rows):
    """utf-8-sig：带 BOM，Excel 双击打开中文不乱码。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(rows)


def backup_if_exists(path):
    """覆盖前把旧文件留一份，防止手写的用例表被无声盖掉。同名备份只留一份，不堆积。"""
    if not os.path.exists(path):
        return
    base, ext = os.path.splitext(path)
    bak = base + "_备份" + ext
    if os.path.exists(bak):
        print(f"  注意：{path} 已存在，将被覆盖。旧备份仍是 {bak}")
        return
    try:
        shutil.copy2(path, bak)
        print(f"  原 {path} 已备份为 {bak}")
    except OSError as e:
        print(f"  注意：{path} 已存在且备份失败（{e}），将继续覆盖")


def preview(title, rows, n=2, width=150):
    """打印拼好的样子。这一步是为了让你在花钱之前亲眼确认拼接对不对。"""
    print(f"\n{title}")
    for r in rows[:n]:
        p = r["prompt"].replace("\n", " | ")
        if len(p) > width:
            p = p[:width] + " …"
        print(f"  [id={r['id']} variant={r['variant'] or '-'}] {p}")


def main():
    ap = argparse.ArgumentParser(description="把原始数据套进提示词模板，生成 prompts.csv")
    ap.add_argument("--input", required=True, help="原始数据：.txt（一行一条）或 .csv")
    ap.add_argument("--text-col", default="", help="CSV 里放评论的列名。不填就用第一列")
    ap.add_argument("--template-a", required=True, help="提示词模板 A（里面要有一处 {评论}）")
    ap.add_argument("--template-b", default="", help="模板 B。填了就做 A/B 对照")
    ap.add_argument("--sample", type=int, default=0, help="随机抽多少条（A/B 建议 30~50）")
    ap.add_argument("--limit", type=int, default=0, help="只用前 N 条，不打乱")
    ap.add_argument("--seed", type=int, default=42, help="抽样种子，固定它才能复现同一批样本")
    ap.add_argument("--out", default="prompts.csv", help="输出的用例表文件名")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"找不到输入文件：{args.input}")

    # ---- 读原始数据 ----
    ext = os.path.splitext(args.input)[1].lower()
    if ext == ".txt":
        items = read_txt_items(args.input)
        src = "纯文本，一行一条"
    elif ext == ".csv":
        items, col = read_csv_items(args.input, args.text_col)
        src = f"CSV 的「{col}」列"
    else:
        sys.exit(f"不支持 {ext}。把 Excel 另存为 .csv，或把评论复制成一个 .txt（一行一条）。")

    if not items:
        sys.exit(f"{args.input} 里没读到内容。")

    print(f"读入 {args.input}（{src}）：{len(items)} 条")

    # ---- 抽样 / 截断 ----
    if args.sample:
        if args.sample < len(items):
            items = sorted(
                random.Random(args.seed).sample(items, args.sample), key=lambda x: x[0]
            )
            print(f"  随机抽 {len(items)} 条（种子 {args.seed}，同参数可复现同一批）")
        else:
            print(f"  抽样数 {args.sample} ≥ 总数，实际用全部")
    elif args.limit:
        items = items[: args.limit]
        print(f"  只取前 {len(items)} 条")

    # ---- 读模板 ----
    tpl_a = read_template(args.template_a)
    tpl_b = read_template(args.template_b) if args.template_b else ""

    # ---- 组装 ----
    if tpl_b:
        rows = build(items, tpl_a, "A") + build(items, tpl_b, "B")
        print(f"\n模式：A/B 对照 —— {len(items)} 条 × 2 版 = {len(rows)} 行")
    else:
        rows = build(items, tpl_a, "")
        print(f"\n模式：单版全量 —— {len(rows)} 行")

    preview("模板 A 拼出来的样子：", build(items, tpl_a, "A" if tpl_b else ""))
    if tpl_b:
        preview("模板 B 拼出来的样子：", build(items, tpl_b, "B"))

    avg = sum(len(r["prompt"]) for r in rows) // len(rows)
    print(f"\n平均每条 prompt {avg} 字")

    # ---- 落盘（覆盖前先备份）----
    backup_if_exists(args.out)
    write_rows(args.out, rows)
    print(f"已写入 {args.out}：{len(rows)} 行")

    # ---- 顺手拦一个常见坑 ----
    if os.path.exists("results.csv"):
        print("\n提醒：本目录已有 results.csv（多半是上一轮任务留下的）。")
        print("  续跑逻辑会把它的旧记录一起写回，跟新结果混在一起。")
        print("  开始新任务前，建议先把它改名留档（如 results_旧任务.csv）。")

    print("\n下一步：双击 2-真跑.cmd")
    if tpl_b:
        print("  不过 A/B 模式下，先把这份对照表跑完、选出更准的那版提示词，")
        print("  再用单版模板跑全量 —— 这样比 1000 行全量对照少花一倍的钱。")


if __name__ == "__main__":
    main()
