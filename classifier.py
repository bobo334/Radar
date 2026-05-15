from dataclasses import dataclass


@dataclass
class CheckResult:
    proxy: str
    success: bool
    country_code: str | None = None
    trust_score: int | None = None
    ip: str | None = None
    rtt: int = 0  # milliseconds


def classify(result: CheckResult) -> str:
    if not result.success:
        return "failed"
    if result.country_code == "CN":
        return "cn"
    score = result.trust_score or 0
    if score == 100:
        return "premium"
    if score >= 60:
        return "good"
    if score >= 30:
        return "normal"
    return "bad"


def format_line(result: CheckResult, level: str, label: str = "none") -> str:
    if label == "none":
        return result.proxy
    cc = result.country_code or "??"
    rtt = result.rtt
    if label == "roxy":
        return f"{result.proxy} {{CC: {cc}, rtt: {rtt}ms, lv: {level}}}"
    # desc
    return f"{result.proxy} # CC: {cc}, rtt: {rtt}ms, lv: {level}"
