import asyncio
import json
import ssl
import struct
import time
from urllib.parse import urlparse

from classifier import CheckResult

API_HOST = "api.ipdata.co"
API_PATH = "/?api-key=eca677b284b3bac29eb72f5e496aa9047f26543605efe99ff2ce35c9"

REQUEST_TEMPLATE = (
    f"GET {API_PATH} HTTP/1.1\r\n"
    f"Host: {API_HOST}\r\n"
    "Accept: */*\r\n"
    "Accept-Encoding: identity\r\n"
    "Accept-Language: zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7\r\n"
    "Origin: https://ipdata.co\r\n"
    "Referer: https://ipdata.co/\r\n"
    "sec-ch-ua: \"Chromium\";v=\"148\", \"Google Chrome\";v=\"148\", \"Not/A)Brand\";v=\"99\"\r\n"
    "sec-ch-ua-mobile: ?0\r\n"
    "sec-ch-ua-platform: \"Windows\"\r\n"
    "sec-fetch-dest: empty\r\n"
    "sec-fetch-mode: cors\r\n"
    "sec-fetch-site: same-site\r\n"
    "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36\r\n"
    "Connection: close\r\n"
    "\r\n"
)


def parse_proxy(proxy_url: str) -> dict:
    if "://" not in proxy_url:
        proxy_url = f"http://{proxy_url}"
    parsed = urlparse(proxy_url)
    return {
        "scheme": parsed.scheme.lower(),
        "host": parsed.hostname,
        "port": parsed.port or (1080 if "socks" in parsed.scheme else 80),
        "username": parsed.username,
        "password": parsed.password,
    }


async def _connect_via_gateway(gateway: dict, target_host: str, target_port: int, timeout: int):
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(gateway["host"], gateway["port"]),
        timeout=timeout,
    )
    connect_req = f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n\r\n"
    writer.write(connect_req.encode())
    await writer.drain()
    response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout)
    if b"200" not in response.split(b"\r\n")[0]:
        writer.close()
        raise ConnectionError(f"Gateway CONNECT failed: {response.decode(errors='ignore').strip()}")
    return reader, writer


async def _socks5_handshake(reader, writer, target_host: str, target_port: int, username=None, password=None, timeout=10):
    if username and password:
        writer.write(b"\x05\x02\x00\x02")
    else:
        writer.write(b"\x05\x01\x00")
    await writer.drain()
    resp = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
    if resp[0] != 0x05:
        raise ConnectionError("Not a SOCKS5 proxy")
    if resp[1] == 0x02:
        uname = username.encode() if username else b""
        passwd = password.encode() if password else b""
        writer.write(b"\x01" + bytes([len(uname)]) + uname + bytes([len(passwd)]) + passwd)
        await writer.drain()
        auth_resp = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
        if auth_resp[1] != 0x00:
            raise ConnectionError("SOCKS5 auth failed")
    elif resp[1] != 0x00:
        raise ConnectionError(f"SOCKS5 unsupported auth method: {resp[1]}")
    host_bytes = target_host.encode()
    writer.write(
        b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + struct.pack("!H", target_port)
    )
    await writer.drain()
    resp = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
    if resp[1] != 0x00:
        raise ConnectionError(f"SOCKS5 connect failed: status {resp[1]}")
    if resp[3] == 0x01:
        await reader.readexactly(4 + 2)
    elif resp[3] == 0x03:
        length = (await reader.readexactly(1))[0]
        await reader.readexactly(length + 2)
    elif resp[3] == 0x04:
        await reader.readexactly(16 + 2)


async def _socks4_handshake(reader, writer, target_host: str, target_port: int, timeout=10):
    import socket
    try:
        ip_bytes = socket.inet_aton(socket.gethostbyname(target_host))
    except Exception:
        ip_bytes = b"\x00\x00\x00\x01"
    writer.write(
        b"\x04\x01" + struct.pack("!H", target_port) + ip_bytes + b"\x00"
    )
    if ip_bytes == b"\x00\x00\x00\x01":
        writer.write(target_host.encode() + b"\x00")
    await writer.drain()
    resp = await asyncio.wait_for(reader.readexactly(8), timeout=timeout)
    if resp[1] != 0x5A:
        raise ConnectionError(f"SOCKS4 connect failed: status {resp[1]:#x}")


async def _http_connect(reader, writer, target_host: str, target_port: int, timeout=10):
    connect_req = f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n\r\n"
    writer.write(connect_req.encode())
    await writer.drain()
    response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout)
    if b"200" not in response.split(b"\r\n")[0]:
        raise ConnectionError(f"HTTP CONNECT failed: {response.decode(errors='ignore').strip()}")


async def _read_http_response(reader, timeout: int) -> tuple[int, str]:
    header_data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout)
    headers_text = header_data.decode(errors="ignore")
    status_line = headers_text.split("\r\n")[0]
    status_code = int(status_line.split(" ")[1])

    content_length = None
    chunked = False
    for line in headers_text.split("\r\n"):
        lower = line.lower()
        if lower.startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())
        if "transfer-encoding" in lower and "chunked" in lower:
            chunked = True

    if content_length is not None:
        body = await asyncio.wait_for(reader.readexactly(content_length), timeout=timeout)
    elif chunked:
        body = b""
        while True:
            size_line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            chunk_size = int(size_line.strip(), 16)
            if chunk_size == 0:
                await reader.readline()
                break
            chunk = await asyncio.wait_for(reader.readexactly(chunk_size), timeout=timeout)
            body += chunk
            await reader.readline()
    else:
        body = await asyncio.wait_for(reader.read(65536), timeout=timeout)

    return status_code, body.decode("utf-8", errors="ignore")


async def check_proxy(proxy: str, gateway: str | None, timeout: int, semaphore: asyncio.Semaphore) -> CheckResult:
    async with semaphore:
        writer = None
        try:
            t0 = time.perf_counter()
            proxy_info = parse_proxy(proxy)

            if gateway:
                gateway_info = parse_proxy(gateway)
                reader, writer = await _connect_via_gateway(
                    gateway_info, proxy_info["host"], proxy_info["port"], timeout
                )
            else:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(proxy_info["host"], proxy_info["port"]),
                    timeout=timeout,
                )

            scheme = proxy_info["scheme"]
            if scheme in ("socks5", "socks5h"):
                await _socks5_handshake(
                    reader, writer, API_HOST, 443,
                    proxy_info["username"], proxy_info["password"], timeout
                )
            elif scheme == "socks4":
                await _socks4_handshake(reader, writer, API_HOST, 443, timeout)
            else:
                await _http_connect(reader, writer, API_HOST, 443, timeout)

            ssl_ctx = ssl.create_default_context()
            transport = writer.transport
            protocol = transport.get_protocol()
            loop = asyncio.get_event_loop()
            new_transport = await loop.start_tls(transport, protocol, ssl_ctx, server_hostname=API_HOST)
            reader._transport = new_transport
            writer._transport = new_transport

            writer.write(REQUEST_TEMPLATE.encode())
            await writer.drain()

            status_code, body = await _read_http_response(reader, timeout)
            rtt = int((time.perf_counter() - t0) * 1000)

            if status_code != 200:
                return CheckResult(proxy=proxy, success=False, rtt=rtt)
            data = json.loads(body)
            return CheckResult(
                proxy=proxy,
                success=True,
                country_code=data.get("country_code"),
                trust_score=data.get("threat", {}).get("scores", {}).get("trust_score"),
                asn_type=data.get("asn", {}).get("type"),
                ip=data.get("ip"),
                rtt=rtt,
            )
        except (Exception, asyncio.CancelledError):
            return CheckResult(proxy=proxy, success=False)
        finally:
            if writer:
                try:
                    writer.close()
                except Exception:
                    pass
