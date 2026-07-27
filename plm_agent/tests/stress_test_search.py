"""
搜索压力测试脚本

支持两种模式:
  1. 经过 Backend (默认): 压测脚本 → Backend /api/execute_search/ → NoahAgent /search_api_mode
  2. 直连 NoahAgent (--direct): 压测脚本 → NoahAgent /search_api_mode

用法:
  # 经过 Backend - 用 token
  python tests/stress_test_search.py --url http://localhost:8000 --token YOUR_TOKEN -c 3 -n 10

  # 经过 Backend - 用用户邮箱自动查 token
  python tests/stress_test_search.py --url http://localhost:8000 --user admin@example.com -c 3 -n 10

  # 直连 NoahAgent
  python tests/stress_test_search.py --url http://localhost:8013 --direct -c 5 -n 20

  # 自定义 prompt
  python tests/stress_test_search.py --url http://localhost:8000 --token YOUR_TOKEN -c 3 -n 10 --prompt "PD-1 immunotherapy"

  # 从文件读取多样化 prompt (每行一个)
  python tests/stress_test_search.py --url http://localhost:8000 --token YOUR_TOKEN -c 3 -n 10 --prompts-file prompts.txt
"""

import argparse
import asyncio
import os
import subprocess
import sys
import time
import statistics
from pathlib import Path

import httpx


DEFAULT_PROMPTS = [
    "EGFR inhibitor clinical trials phase 3",
    "PD-1 immunotherapy latest research 2024",
    "GLP-1 receptor agonist cardiovascular outcomes",
    "CRISPR gene therapy sickle cell disease",
    "ADC antibody drug conjugate HER2",
    "CAR-T cell therapy solid tumors",
    "mRNA vaccine cancer immunotherapy",
    "NASH nonalcoholic steatohepatitis drug pipeline",
    "Alzheimer amyloid beta antibody treatment",
    "Bispecific antibody oncology clinical development",
]


async def send_request(
    client: httpx.AsyncClient,
    request_id: int,
    url: str,
    headers: dict,
    body: dict,
    direct: bool,
) -> dict:
    """Send a single request and return timing + result info."""
    start = time.monotonic()
    status = "success"
    error = ""
    http_code = 0

    try:
        resp = await client.post(url, json=body, headers=headers)
        http_code = resp.status_code
        result = resp.json()

        if direct:
            if result.get("error"):
                status = "fail"
                error = result["error"]
        else:
            if result.get("status") != "success":
                status = "fail"
                error = result.get("error", "unknown")

    except httpx.TimeoutException:
        status = "timeout"
        error = "request timed out"
    except Exception as e:
        status = "error"
        error = str(e)

    elapsed = time.monotonic() - start
    print(f"  [#{request_id:03d}] {status:<8} {elapsed:7.1f}s  HTTP {http_code}  {error[:80] if error else ''}")
    return {"id": request_id, "status": status, "elapsed": elapsed, "http_code": http_code, "error": error}


async def run_stress_test(args):
    prompts = DEFAULT_PROMPTS
    if args.prompts_file:
        prompts = [line.strip() for line in Path(args.prompts_file).read_text().splitlines() if line.strip()]
    if args.prompt:
        prompts = [args.prompt]

    base_url = args.url.rstrip("/")
    if args.direct:
        url = f"{base_url}/search_api_mode"
    else:
        url = f"{base_url}/api/execute_search/"

    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["Authorization"] = f"Token {args.token}"

    print(f"Target:      {url}")
    print(f"Mode:        {'直连 NoahAgent' if args.direct else '经过 Backend'}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Total:       {args.total}")
    print(f"Timeout:     {args.timeout}s")
    print(f"Prompts:     {len(prompts)} unique queries")
    print("-" * 80)

    semaphore = asyncio.Semaphore(args.concurrency)
    results = []

    async def bounded_request(req_id):
        async with semaphore:
            prompt = prompts[req_id % len(prompts)]
            if args.direct:
                body = {"prompt": prompt, "params": {"language": args.language}}
            else:
                body = {"user_prompt": prompt, "params": {"language": args.language}}
            return await send_request(client, req_id, url, headers, body, args.direct)

    timeout = httpx.Timeout(args.timeout, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        start_all = time.monotonic()
        tasks = [bounded_request(i) for i in range(args.total)]
        results = await asyncio.gather(*tasks)
        total_time = time.monotonic() - start_all

    # --- 统计 ---
    print("=" * 80)
    successes = [r for r in results if r["status"] == "success"]
    failures = [r for r in results if r["status"] != "success"]
    all_times = [r["elapsed"] for r in results]
    success_times = [r["elapsed"] for r in successes]

    print(f"Total time:    {total_time:.1f}s")
    print(f"Requests:      {len(results)} total, {len(successes)} success, {len(failures)} fail")
    print(f"Throughput:    {len(results) / total_time:.2f} req/s")

    if all_times:
        all_sorted = sorted(all_times)
        print(f"\nLatency (all requests):")
        print(f"  Min:    {min(all_times):7.1f}s")
        print(f"  Avg:    {statistics.mean(all_times):7.1f}s")
        print(f"  Median: {statistics.median(all_times):7.1f}s")
        print(f"  P95:    {all_sorted[int(len(all_sorted) * 0.95)]:7.1f}s")
        print(f"  Max:    {max(all_times):7.1f}s")

    if success_times and len(success_times) != len(all_times):
        print(f"\nLatency (success only):")
        print(f"  Avg:    {statistics.mean(success_times):7.1f}s")
        print(f"  Max:    {max(success_times):7.1f}s")

    if failures:
        print(f"\nFailures:")
        for r in failures:
            print(f"  [#{r['id']:03d}] {r['status']} HTTP {r['http_code']}: {r['error'][:100]}")


def _find_backend_dir() -> Path:
    """定位 Backend 项目目录. 从 __file__ 和 cwd 逐级向上搜索."""
    roots = {Path(__file__).resolve().parent, Path(os.getcwd()).resolve()}
    candidates = []
    for root in roots:
        p = root
        while p != p.parent:
            candidates.append(p / "Backend")
            p = p.parent
    for d in candidates:
        if (d / "manage.py").exists():
            return d
    sys.exit("找不到 Backend 目录 (需要 manage.py), 请用 --token 手动指定")


def _run_django_shell(cmd: str) -> str:
    """执行 Django manage.py shell 命令并返回 stdout."""
    backend_dir = _find_backend_dir()
    try:
        result = subprocess.run(
            [sys.executable, "manage.py", "shell", "-c", cmd],
            cwd=str(backend_dir),
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip()
        if result.returncode != 0 or not output:
            sys.exit(f"Django shell 执行失败: {result.stderr.strip()}")
        return output
    except FileNotFoundError:
        sys.exit("python 不可用, 请用 --token 手动指定")
    except subprocess.TimeoutExpired:
        sys.exit("Django shell 执行超时")


def resolve_token(user_email: str) -> str:
    """通过用户邮箱查询 auth token."""
    cmd = (
        f'from rest_framework.authtoken.models import Token; '
        f'print(Token.objects.get(user__email="{user_email}").key)'
    )
    return _run_django_shell(cmd)


def ensure_user_permission(token: str) -> str:
    """通过 token 反查用户, 确保 trial_tier=13, 返回用户邮箱."""
    cmd = (
        f'from rest_framework.authtoken.models import Token; '
        f't = Token.objects.select_related("user").get(key="{token}"); '
        f'u = t.user; '
        f'changed = ""; '
        f'exec("if u.trial_tier != 13:\\n u.trial_tier = 13\\n u.save()\\n changed = \\" (trial_tier updated to 13)\\""); '
        f'print(f"{{u.email}}{{changed}}")'
    )
    return _run_django_shell(cmd)


def main():
    parser = argparse.ArgumentParser(description="搜索压力测试")
    parser.add_argument("--url", required=True, help="Backend or NoahAgent base URL")
    parser.add_argument("--token", default="", help="Backend auth token")
    parser.add_argument("--user", default="", help="用户邮箱, 自动从 Backend DB 查 token")
    parser.add_argument("--direct", action="store_true", help="直连 NoahAgent, 跳过 Backend")
    parser.add_argument("-c", "--concurrency", type=int, default=3, help="并发数 (default: 3)")
    parser.add_argument("-n", "--total", type=int, default=10, help="总请求数 (default: 10)")
    parser.add_argument("--timeout", type=int, default=900, help="单请求超时秒数 (default: 900)")
    parser.add_argument("--prompt", default="", help="自定义单个 prompt")
    parser.add_argument("--prompts-file", default="", help="prompt 列表文件, 每行一个")
    parser.add_argument("--language", default="zh", help="语言 (default: zh)")
    args = parser.parse_args()

    if not args.direct:
        if args.user and not args.token:
            print(f"正在查询 {args.user} 的 token...")
            args.token = resolve_token(args.user)
            print(f"Token: {args.token[:8]}...")
        if not args.token:
            parser.error("经过 Backend 模式需要 --token 或 --user, 或使用 --direct 直连 NoahAgent")
        # 通过 token 反查用户, 确保有权限
        print(f"正在验证用户权限...")
        user_info = ensure_user_permission(args.token)
        print(f"User: {user_info}")

    asyncio.run(run_stress_test(args))


if __name__ == "__main__":
    main()
