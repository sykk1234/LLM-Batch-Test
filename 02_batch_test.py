# -*- coding: utf-8 -*-
"""
02 · 批量测试 —— 把 1 条 prompt 变成 500 条，并发跑完，落成一张表。

这是你「补齐工程理解」的第一个真家伙。不用背命令，双击两个文件就够了：

    1-先试跑.cmd   不花钱、不用 key。只为把流程跑通。注意 output 列是假答案！
    2-真跑.cmd     在 .env 里填好 key 之后双击，output 列才是模型真写的答案

想用命令行（等你要调参数时再回来）：

    # 试跑：不花钱，验证流程。特意用另一个输出文件名，别和真结果混在一起
    python 02_batch_test.py --input prompts.csv --output results_试跑.csv --dry-run

    # 真跑但先只跑 5 条，确认花的是自己以为的钱
    python 02_batch_test.py --input prompts.csv --output results.csv --limit 5

    # 全量
    python 02_batch_test.py --input prompts.csv --output results.csv --workers 8

它比「写个 for 循环」值钱的地方就三点，也是你面试/汇报时能讲的东西：
  1. 断点续跑 —— 中途 Ctrl+C，重跑只补没成功的，绝不重复烧钱
  2. 失败重试 —— 500 条里总有几条超时/限流，不重试等于白跑
  3. 全量留痕 —— 输入、输出、耗时、token、报错全落表，事后才能分析

改哪里能干什么：
  · 换模型 → 改 .env，或命令加 --model deepseek-chat
  · 换任务 → 改 prompts.csv 的 prompt 列
  · 对比两版提示词 → prompts.csv 里出 A/B 两行同 id 不同 variant，跑完按 variant 分组看
"""

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def load_env_file(path):
    """极简 .env 解析器 —— 零依赖，不需要装 python-dotenv。

    格式：每行一条 KEY=VALUE，忽略空行和 # 注释行。
    系统里已有的环境变量优先，不会被文件覆盖（setdefault 而不是直接赋值）。

    为什么自己写这 12 行：少一个依赖 = 少一步安装 = 少一个能卡住你的地方。
    """
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# 配置从脚本同目录的 .env 读。没有这个文件也能跑 —— dry-run 不需要 key
load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

API_KEY = os.getenv("LLM_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "")

# 结果表的列。事先定死，是为了让「跑第二遍」「换模型再跑」产出的表结构完全一致，能直接对比
RESULT_FIELDS = [
    "uid", "id", "variant", "prompt", "output", "model",
    "status", "latency_s", "prompt_tokens", "completion_tokens", "error",
]

# 试跑写下的 output 都带这些前缀。用途见 is_fake()。
FAKE_MARKERS = ("【假答案", "[dry-run]")


def is_fake(output):
    """判断一行是不是「试跑产生的假答案」。

    为什么要靠内容判断、而不是只看 status：早期版本的试跑把 status 写成了 ok，
    历史 results.csv 里就会留下一批「假的 ok」。真跑读到它们会误以为已完成，
    于是 16 条全部跳过、一次 API 都不调，最后还报「成功 16」——
    你配了半天 key，拿到的却是假答案。这是实际踩到的坑。
    """
    text = (output or "").strip()
    return any(text.startswith(m) for m in FAKE_MARKERS)

_client = None

# 最近一次致命错误的排查建议，供 main 打印。用模块级变量是因为
# run_one 在工作线程里跑，没办法直接往主线程传额外信息。
_fatal_advice = ""


def check_key_format():
    """按平台特征做一次格式自检。不花钱，但能提前拦下最常见的填错。

    为什么值得单独写这一步：格式不对的 key 无论如何都会 401，
    但它在 .env 里"看起来是填了的"，用户会以为是代码问题或网络问题。
    在发请求之前直接说出来，比让他等一次网络往返再猜要好得多。
    """
    problems = []

    if not API_KEY:
        problems.append("LLM_API_KEY 是空的。检查 .env 里那一行等号后面有没有值")
    if not BASE_URL:
        problems.append("LLM_BASE_URL 是空的。检查 .env 里那一行")

    if API_KEY and "bigmodel.cn" in BASE_URL and "." not in API_KEY:
        # 依据：智谱官方 JWT 示例里直接 apikey.split(".")，
        # 说明 key 由「id.密钥」两段拼成，中间必有一个点号。
        problems.append(
            f"智谱的 key 必须含一个点号，你现在这个没有点号（长度 {len(API_KEY)}）。\n"
            "     形如 xxxxxxxx.xxxxxxxx。你多半复制的是 key 的 ID，不是 key 本身。\n"
            "     回控制台 API Keys 页面，复制那一整串。"
        )

    if problems:
        print("\n[配置自检没通过] 先修这几项（本次没发任何请求，没花钱）：\n")
        for p in problems:
            print("  ·", p)
        print()
        sys.exit(1)


def get_client():
    """懒加载。dry-run 时不需要 key，所以不能写在模块顶层。"""
    global _client
    if _client is None:
        if not API_KEY or not BASE_URL:
            sys.exit("缺少 LLM_API_KEY / LLM_BASE_URL —— 请先把 .env.example 复制成 .env 并填好")
        from openai import OpenAI

        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


def call_api(prompt, model):
    """真正发起一次请求。注意：这里没有任何业务判断，只负责「送进去、拿回来」。"""
    resp = get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": os.getenv("LLM_SYSTEM_PROMPT", "")},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    text = resp.choices[0].message.content or ""

    # 不是所有 OpenAI 兼容服务都返回 usage，所以用 getattr 兜底，缺了就当 0
    usage = getattr(resp, "usage", None)
    ptok = getattr(usage, "prompt_tokens", 0) or 0
    ctok = getattr(usage, "completion_tokens", 0) or 0
    return text, ptok, ctok


class FatalAPIError(Exception):
    """不可恢复的错误：重试没用，继续跑剩余用例也没用。

    这类错误和「超时」「限流」有本质区别 —— 后者重试就可能成功，
    前者重试 100 次结果一样。批量跑的 500 条里如果 key 是错的，
    500 条会全部失败，每条还白等 1+2+4=7 秒重试。
    """

    def __init__(self, kind, message, advice):
        super().__init__(message)
        self.kind = kind
        self.advice = advice


# 致命错误 → 给人看的排查建议（不是给机器看的）
FATAL_ADVICE = {
    "AuthenticationError": (
        "API Key 不对。检查 .env 里 LLM_API_KEY 那一行：\n"
        "      · 必须复制【完整】的 key。智谱的 key 中间有一个点号，形如 xxxxxxxx.xxxxxxxx\n"
        "      · 只有 32 位、不含点号 → 那是 key 的 ID，不是 key 本身\n"
        "      · 等号两边不要加空格，值不要用引号包起来\n"
        "      · 也确认这个 key 和 LLM_BASE_URL 是同一家平台的"
    ),
    "PermissionDeniedError": "这个 key 没有调用该模型的权限（可能需要在控制台开通该模型）",
    "NotFoundError": "模型名不存在。检查 .env 里 LLM_MODEL 是否拼写正确",
    "BadRequestError": "请求参数有问题。最常见的是模型名写错",
}


def classify_error(e):
    """判断错误是否致命。返回 (是否致命, 排查建议)。"""
    name = type(e).__name__
    if name in FATAL_ADVICE:
        return True, FATAL_ADVICE[name]
    # openai 库有时会把 HTTP 状态包成别的异常类型，所以再按状态码兜底判断
    status = getattr(e, "status_code", None)
    if status == 401:
        return True, FATAL_ADVICE["AuthenticationError"]
    if status == 403:
        return True, FATAL_ADVICE["PermissionDeniedError"]
    if status == 404:
        return True, FATAL_ADVICE["NotFoundError"]
    if status == 400:
        return True, FATAL_ADVICE["BadRequestError"]
    # 其余（超时、429、5xx、网络抖动）都是「重试可能好」的，交给重试层
    return False, ""


def call_with_retry(prompt, model, max_retries=3):
    """指数退避重试：等 2s → 4s，第三次失败就放弃。

    但只有「重试可能成功」的错误才重试。key 错、模型名错这类问题
    重试只是浪费时间，直接抛 FatalAPIError 让上层停掉整批。
    """
    for attempt in range(1, max_retries + 1):
        try:
            return call_api(prompt, model)
        except Exception as e:
            fatal, advice = classify_error(e)
            if fatal:
                raise FatalAPIError(type(e).__name__, str(e), advice) from e
            if attempt == max_retries:
                raise  # 三次都失败，交给上层记进 error 列，不要吞掉
            wait = 2 ** attempt
            print(f"      第 {attempt} 次失败（{type(e).__name__}），{wait}s 后重试", file=sys.stderr)
            time.sleep(wait)


def to_uid(row):
    """真正的唯一键：同一道题的 A/B 两个版本共用 id、靠 variant 区分。
    去重、断点续跑、结果落盘都必须用它 —— 只用 id 会让 B 覆盖 A（实测踩到过）。
    只在这一处定义，run_one() 和 main() 都来调它，免得两边各写一遍写出不一样的结果。"""
    rid = str(row.get("id", "")).strip()
    variant = str(row.get("variant", "")).strip()
    return f"{rid}-{variant}" if variant else rid


def run_one(row, model, dry_run, index, total):
    """跑一行，返回一条结果记录。无论成功失败都返回，绝不抛异常。"""
    rid = str(row.get("id", "")).strip()
    variant = str(row.get("variant", "")).strip()
    prompt = str(row.get("prompt", "")).strip()
    uid = to_uid(row)

    rec = {
        "uid": uid, "id": rid, "variant": variant, "prompt": prompt,
        "output": "", "model": model, "status": "ok", "latency_s": "",
        "prompt_tokens": 0, "completion_tokens": 0, "error": "",
    }

    t0 = time.time()
    try:
        if dry_run:
            time.sleep(0.3)  # 假装在调 API，让整个流程的手感跟真跑一致
            text = "【假答案·试跑模式】这一格本该是模型写的。试跑不调用大模型，所以没有真结果。"
            ptok = ctok = 0
            # 关键：试跑必须用 "dry" 而不是 "ok"。否则真跑启动时会把试跑结果
            # 误判成「已完成」而把全部用例跳过 —— 表现为「真跑 0 条待跑」。
            rec["status"] = "dry"
        else:
            text, ptok, ctok = call_with_retry(prompt, model)
        rec["output"] = text
        rec["prompt_tokens"] = ptok
        rec["completion_tokens"] = ctok
    except FatalAPIError as e:
        # 致命错误：单独标出来，让 main 有机会停掉整批
        rec["status"] = "fatal"
        rec["error"] = f"{e.kind}: {e}"
        global _fatal_advice
        _fatal_advice = e.advice
    except Exception as e:
        rec["status"] = "error"
        rec["error"] = f"{type(e).__name__}: {e}"

    rec["latency_s"] = round(time.time() - t0, 2)
    flag = {"ok": "ok  ", "dry": "试跑", "fatal": "致命", "error": "FAIL"}.get(rec["status"], "FAIL")
    print(f"[{index}/{total}] {flag} {uid:<7} {rec['latency_s']:>6}s")
    return rec


def read_rows(path):
    """utf-8-sig 是关键：带 BOM，Windows 上 Excel 双击打开中文不乱码。"""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def check_writable(path):
    """开跑前先确认结果文件写得进去 —— 这一步能救命。

    为什么必须放在调用 API 之前：Excel / WPS 打开 CSV 时会**独占**这个文件。
    如果跑完全部用例才发现写不进去，API 的钱已经花掉，结果却全丢了。
    实测踩到：Excel 打开着 results.csv，脚本跑完 16 条调用后崩在保存，
    退出码非 0，表里还是旧数据 —— 看起来像「跑成功但没结果」。

    宁可开跑前就拦住：一分钱不花，说清楚原因。
    """
    try:
        with open(path, "a", encoding="utf-8-sig"):
            pass
    except PermissionError:
        print(f"\n[已停止] 结果文件写不进去：{path}")
        print("原因：它正被 Excel / WPS 打开着（Office 会独占文件）。")
        print("解决：关掉那个表格窗口，再重新运行。")
        print("\n本次没有发起任何 API 调用，没花钱。")
        sys.exit(1)
    except OSError as e:
        print(f"\n[已停止] 结果文件无法访问：{path}\n{e}")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="批量调用大模型 API 并落表")
    ap.add_argument("--input", default="prompts.csv", help="输入用例表，需含 id/variant/prompt 列")
    ap.add_argument("--output", default="results.csv", help="结果表，已存在的会被续跑逻辑复用")
    ap.add_argument("--model", default=os.getenv("LLM_MODEL", "ernie-4.0-turbo-8k"))
    ap.add_argument("--workers", type=int, default=8, help="并发数。调太高会触发限流，8 是安全的起点")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条。先小样本验证，再全量")
    ap.add_argument("--dry-run", action="store_true", help="不真调 API，只验证流程")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"找不到输入文件：{args.input}")

    # 开跑前先拦住「结果文件被 Excel 占用」这类问题，别等调完 API 才发现写不进去
    check_writable(args.output)

    # 真跑才需要检查 key —— 试跑是故意不用 key 的
    if not args.dry_run:
        check_key_format()

    rows = read_rows(args.input)
    if args.limit:
        rows = rows[: args.limit]
    input_ids = [to_uid(r) for r in rows]

    # ---- 断点续跑：上次真跑成功的 uid 才跳过，不重复烧钱 ----
    # 双重判定：status 必须是 ok，且 output 不能是试跑的假答案。
    # 只认 status 不够 —— 历史文件里可能有「假的 ok」（见 is_fake 的说明）。
    done = {}
    dry_seen = 0
    if os.path.exists(args.output):
        for r in read_rows(args.output):
            uid = str(r.get("uid", "")).strip()
            if not uid:
                continue
            fake = is_fake(r.get("output", ""))
            if fake or r.get("status") == "dry":
                dry_seen += 1
            elif r.get("status") == "ok":
                done[uid] = r
    todo = [r for r in rows if to_uid(r) not in done]

    print(f"输入 {len(rows)} 条 ｜ 上次真跑完成 {len(done)} 条 ｜ 本轮待跑 {len(todo)} 条")
    if dry_seen:
        print(f"（表里另有 {dry_seen} 条是试跑的假答案，不算完成，本轮会重跑）")
    print(f"模型 {args.model} ｜ 并发 {args.workers}{' ｜ DRY-RUN（不花钱）' if args.dry_run else ''}")
    print("-" * 56)

    results = dict(done)

    def flush():
        """每完成一条就落盘一次。中断最多丢一条，这是断点续跑真正生效的前提。"""
        ordered = [results[i] for i in input_ids if i in results]
        ordered += [v for k, v in results.items() if k not in input_ids]
        write_rows(args.output, ordered)

    # ---- 预检：先单独跑 1 条，别等并发跑完一整批才发现 key 填错了 ----
    # 为什么值得多这几行：key 错 / 模型名错这类问题是「必然全错」的。
    # 不加预检的话，16 条会并发全跑一遍、每条还退避重试 1+2+4 秒，
    # 你干等两分钟，最后得到的还是同一个错误信息。实测就这么白等过。
    if todo and not args.dry_run:
        print("先预检 1 条，确认 key 和模型名可用……")
        probe = run_one(todo[0], args.model, False, 1, 1)
        results[probe["uid"]] = probe
        flush()
        if probe["status"] == "fatal":
            print("\n" + "=" * 56)
            print("整批已停止：第 1 条就是致命错误，继续跑剩下 "
                  f"{len(todo) - 1} 条必然也全错。")
            print("=" * 56)
            print(f"\n报错原文：\n  {probe['error']}\n")
            if _fatal_advice:
                print(f"怎么修：\n  {_fatal_advice}\n")
            print(f"改好 .env 后重新双击 2-真跑.cmd 即可（已成功的会跳过，不重复花钱）。")
            sys.exit(1)
        if probe["status"] == "ok":
            print("预检通过。\n")
            todo = todo[1:]  # 第一条已经跑完并落盘，不重复调
        else:
            print(f"预检这条失败了（{probe['status']}），但看起来不是致命错误，继续跑完剩下的。\n")
            todo = todo[1:]

    if todo:
        t_start = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run_one, r, args.model, args.dry_run, i, len(todo))
                       for i, r in enumerate(todo, 1)]
            for fut in as_completed(futures):  # 谁先跑完先收谁，不按提交顺序
                rec = fut.result()
                results[rec["uid"]] = rec
                flush()
        print(f"本轮到 {round(time.time() - t_start, 1)}s 全部返回")

    # ---- 汇总 ----
    all_rows = list(results.values())
    ok_rows = [r for r in all_rows if r["status"] in ("ok", "dry")]
    dry_rows = [r for r in all_rows if r["status"] == "dry"]
    err_rows = [r for r in all_rows if r["status"] == "error"]
    fatal_rows = [r for r in all_rows if r["status"] == "fatal"]
    ptok = sum(int(r["prompt_tokens"] or 0) for r in all_rows)
    ctok = sum(int(r["completion_tokens"] or 0) for r in all_rows)
    lats = [float(r["latency_s"]) for r in all_rows if r["latency_s"] != ""]
    avg_lat = round(sum(lats) / len(lats), 2) if lats else 0

    print("-" * 56)
    print(f"成功 {len(ok_rows)} ｜ 失败 {len(err_rows)} ｜ 致命 {len(fatal_rows)} ｜ 合计 {len(all_rows)}")
    print(f"平均耗时 {avg_lat}s ｜ token 输入 {ptok} / 输出 {ctok} / 合计 {ptok + ctok}")
    print(f"结果已写入 {args.output}（Excel 可直接打开）")

    if dry_rows:
        print(f"\n提醒：本轮是试跑，{len(dry_rows)} 条 output 全是假答案。")
        print("要拿真结果 → 申请一个 API key 填进 .env，然后双击 2-真跑.cmd")
    if fatal_rows:
        print(f"\n有 {len(fatal_rows)} 条是致命错误（key 或模型名的问题，重试没有意义）。")
        if _fatal_advice:
            print(f"怎么修：\n  {_fatal_advice}")
    if err_rows:
        print(f"\n有 {len(err_rows)} 条失败，看结果表的 error 列。修好后重跑同一条命令会自动续跑（不重复花钱）。")


if __name__ == "__main__":
    main()
