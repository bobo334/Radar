import argparse
import asyncio
import logging
import os
import sys

logging.getLogger("asyncio").setLevel(logging.CRITICAL)

from checker import check_proxy
from classifier import CheckResult, classify, format_line
from parser import load_proxies

RESULT_DIR = "./result"

FILE_MAP = {
    "premium": "premium_proxies.txt",
    "good": "good_proxies.txt",
    "normal": "normal_proxies.txt",
    "bad": "bad_proxies.txt",
    "cn": "cn_proxies.txt",
    "failed": "failed_proxy.txt",
}


def setup_result_dir():
    os.makedirs(RESULT_DIR, exist_ok=True)


def write_results(buckets: dict[str, list[CheckResult]], label: str):
    for category, results in buckets.items():
        results.sort(key=lambda r: r.rtt)
        filepath = os.path.join(RESULT_DIR, FILE_MAP[category])
        with open(filepath, "w", encoding="utf-8") as f:
            for r in results:
                f.write(format_line(r, category, label) + "\n")


async def run(files: list[str], concurrency: int, timeout: int, gateway: str | None, label: str = "none"):
    proxies = load_proxies(files)
    total = len(proxies)
    if total == 0:
        print("No proxies found in input files.")
        return

    mode = f"Gateway: {gateway}" if gateway else "Direct"
    print(f"Loaded {total} proxies. {mode}")
    print(f"Starting check (concurrency={concurrency}, timeout={timeout}s)...")
    setup_result_dir()

    semaphore = asyncio.Semaphore(concurrency)
    counts = {"premium": 0, "good": 0, "normal": 0, "bad": 0, "cn": 0, "failed": 0}
    buckets: dict[str, list[CheckResult]] = {k: [] for k in FILE_MAP}
    checked = 0

    async def process(proxy: str):
        nonlocal checked
        result = await check_proxy(proxy, gateway, timeout, semaphore)
        category = classify(result)
        buckets[category].append(result)
        counts[category] += 1
        checked += 1
        status = " | ".join(f"{k}:{v}" for k, v in counts.items())
        sys.stdout.write(f"\r[{checked}/{total}] {status}")
        sys.stdout.flush()

    tasks = [asyncio.create_task(process(p)) for p in proxies]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass

    write_results(buckets, label)
    print(f"\n[{checked}/{total}] Done. Results saved to ./result/")


def main():
    parser = argparse.ArgumentParser(
        prog="proxy-radar",
        description="Proxy Radar - Batch proxy checker with ipdata intelligence",
    )
    parser.add_argument("-f", "--file", action="append", required=True, help="Proxy source file (can specify multiple)")
    parser.add_argument("-g", "--gateway", default=None, help="Local gateway proxy (optional, e.g. http://127.0.0.1:7890)")
    parser.add_argument("-c", "--concurrency", type=int, default=50, help="Concurrent checks (default: 50)")
    parser.add_argument("-t", "--timeout", type=int, default=20, help="Request timeout in seconds (default: 20)")
    parser.add_argument("-l", "--label", choices=["none", "roxy", "desc"], default="none", help="Label format: none, roxy ({...}), desc (# comment)")
    args = parser.parse_args()

    try:
        asyncio.run(run(args.file, args.concurrency, args.timeout, args.gateway, args.label))
    except KeyboardInterrupt:
        print("\nInterrupted. Partial results saved to ./result/")


if __name__ == "__main__":
    main()
