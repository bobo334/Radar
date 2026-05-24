<div align="center">
    <h1>Cuz Radar</h1>
    <h5>A Open Source Proxy Radar</h5>
</div>

## About

批量代理质量检测工具。通过本地网关代理链式访问 ipdata API，获取每个代理的出口 IP 信息与信任评分，自动分类输出。

## Install

```bash
uv sync
```

## Usage

```bash
# 基本用法
python main.py -f proxies.txt

# 多文件合并检测
python main.py -f source1.txt -f source2.txt

# 自定义参数
python main.py -f proxies.txt -c 100 -t 30 -g http://127.0.0.1:7890 -l roxy
```

### Arguments

| Flag | Description | Default |
|------|-------------|---------|
| `-f, --file` | Proxy source file (repeatable) | Required |
| `-g, --gateway` | Local gateway proxy | `http://127.0.0.1:7890` |
| `-c, --concurrency` | Concurrent checks | 50 |
| `-t, --timeout` | Timeout in seconds | 20 |
| `-l, --label` | Label format: `none` / `roxy` / `desc` | `none` |

### Label Formats

- `none` — proxy address only
- `roxy` — `socks5://host:port {CC: US, rtt: 320ms, lv: premium}`
- `desc` — `socks5://host:port # CC: US, rtt: 320ms, lv: premium`

## Proxy Input Format

One proxy per line:

```
http://host:port
http://user:pass@host:port
socks5://host:port
socks4://host:port
host:port              # defaults to http
```

Lines starting with `#` are comments.

## Classification

| Level | Condition | Output |
|-------|-----------|--------|
| home | asn.type = isp | `home_proxies.txt` |
| premium | trust_score = 100 | `premium_proxies.txt` |
| good | trust_score >= 60 | `good_proxies.txt` |
| normal | trust_score >= 30 | `normal_proxies.txt` |
| bad | trust_score < 30 | `bad_proxies.txt` |
| cn | country_code = CN | `cn_proxies.txt` |
| failed | Connection error/timeout | `failed_proxy.txt` |

Results sorted by RTT (lowest first), saved to `./result/`.

## How It Works

```
Machine → Gateway(7890) → Test Proxy → ipdata API
```

Routes through a local gateway (e.g. Clash) to reach test proxies behind network restrictions, then queries ipdata via the test proxy to evaluate its exit IP.

## License

AGPL-3.0
