from __future__ import annotations

import ssl
import threading
from urllib.parse import urlsplit

import truststore

# Provider 的全部连接（三种协议的模型调用与模型列表）信任操作系统的证书库（truststore，D17）：私有 CA 与企业 TLS 检查代理的
# 证书装在系统证书库中即可；truststore 另外信任经 load_verify_locations 在进程内加入的 CA。
# 同一个线程的连接共用一个上下文：truststore 建立每个连接时临时改写上下文内部的校验设置再恢复，wrap_bio 不加锁
# （truststore #209、#221），多个线程共用一个上下文时可能互相读到或恢复成关闭校验的设置；一个线程的连接在它的事件循环中
# 依次建立，不会交错。共用也避免 Chat Completions 与 Messages 每次调用新建客户端时各自建立上下文。
# openai 的客户端使用 httpx，anthropic 的客户端使用 httpx2，两者都使用这个上下文；httpcore 与 httpcore2 建立每个 TLS 连接时
# 在上下文上设置 ALPN，全部客户端都只用 HTTP/1.1，设置的值相同
_THREAD = threading.local()


def ssl_context() -> ssl.SSLContext:
    context = getattr(_THREAD, "context", None)
    if context is None:
        context = _THREAD.context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return context


def certificate_verification_failed(exc: BaseException) -> bool:
    # TLS 握手中证书校验失败：连接错误的原因链中有 ssl.SSLCertVerificationError。
    # httpx 与 httpx2 以 __cause__ 连到 httpcore 的错误，httpcore 与 httpcore2 以 __context__ 连到 ssl 的错误
    seen: set[int] = set()
    cause: BaseException | None = exc
    while cause is not None and id(cause) not in seen:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return True
        seen.add(id(cause))
        cause = cause.__cause__ or cause.__context__
    return False


def service_address(url: str) -> str:
    # 证书属于服务的主机：错误中写明协议、主机与端口
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
