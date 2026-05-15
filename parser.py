from typing import List


def parse_proxy_line(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" not in line:
        line = f"http://{line}"
    return line


def load_proxies(files: List[str]) -> List[str]:
    seen = set()
    proxies = []
    for filepath in files:
        with open(filepath, "r", encoding="utf-8") as f:
            for raw_line in f:
                proxy = parse_proxy_line(raw_line)
                if proxy and proxy not in seen:
                    seen.add(proxy)
                    proxies.append(proxy)
    return proxies
