from __future__ import annotations

import asyncio
import socket
from typing import AsyncGenerator, Optional, Tuple
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from psycopg_pool import AsyncConnectionPool


def create_pool(database_url: str) -> AsyncConnectionPool:
    # min_size/max_size 可按部署环境再调；先保持简单可用
    return AsyncConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"connect_timeout": 10},
    )


async def open_pool(pool: AsyncConnectionPool) -> None:
    await pool.open()


async def close_pool(pool: Optional[AsyncConnectionPool]) -> None:
    if pool is not None:
        await pool.close()


def connection_target_summary(conninfo: str) -> str:
    """日志与错误提示用：不含密码。"""
    p = urlparse(conninfo.strip())
    host = p.hostname or "（缺失）"
    port = p.port if p.port is not None else "（默认 5432）"
    db = (p.path or "").lstrip("/") or "（缺失）"
    return f"host={host} port={port} dbname={db}"


def validate_database_url(conninfo: str) -> Optional[str]:
    """格式问题返回中文说明；通过则返回 None。"""
    s = conninfo.strip()
    if not s:
        return "DATABASE_URL 为空：请在环境变量或项目根目录 .env 中设置。"
    scheme = (s.split(":", 1)[0] if ":" in s else "").lower()
    if scheme not in ("postgresql", "postgres"):
        return "DATABASE_URL 应以 postgresql:// 或 postgres:// 开头。"
    parsed = urlparse(s)
    if not parsed.hostname:
        return (
            "DATABASE_URL 中无法解析出主机名：请检查 @ 之后、端口之前的域名或 IP 是否完整；"
            "若密码中含有 @、:、/、# 等特殊字符，需进行 URL 编码后再写入连接串。"
        )
    return None


async def dns_precheck(conninfo: str) -> Optional[str]:
    """启动时预检 DNS，避免连接池在坏主机名上反复重试刷屏。"""
    parsed = urlparse(conninfo.strip())
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port if parsed.port is not None else 5432
    try:
        await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return (
            f"无法解析数据库主机名（{connection_target_summary(conninfo)}）。"
            f"系统报错：{exc}。请核对控制台复制的连接串是否完整、本机网络/DNS 是否正常，"
            "并确认没有把未替换的占位符（如 HOST）当作主机名。"
        )
    return None


def _root_exception(exc: BaseException) -> BaseException:
    root: BaseException = exc
    while root.__cause__ is not None:
        root = root.__cause__
    return root


def format_pool_open_error(conninfo: str, exc: BaseException) -> str:
    summary = connection_target_summary(conninfo)
    root = _root_exception(exc)
    if isinstance(root, socket.gaierror):
        return (
            f"数据库 DNS 解析失败（{summary}）：{root}。"
            "请检查 DATABASE_URL 中的主机名，以及密码特殊字符是否已 URL 编码。"
        )
    return f"无法打开数据库连接池（{summary}）：{exc}"


async def create_and_open_pool(conninfo: str) -> Tuple[Optional[AsyncConnectionPool], Optional[str]]:
    """成功返回 (pool, None)；失败关闭半成品池并返回 (None, 中文错误说明)。"""
    pool = create_pool(conninfo)
    try:
        await open_pool(pool)
    except BaseException as exc:
        await close_pool(pool)
        return None, format_pool_open_error(conninfo, exc)
    return pool, None


def get_pool_from_app(request: Request) -> Optional[AsyncConnectionPool]:
    return getattr(request.app.state, "db_pool", None)


async def get_db(request: Request) -> AsyncGenerator[AsyncConnectionPool, None]:
    """依赖注入：路由内 `async with (await pool.connection())` 执行 SQL。"""
    init_err: Optional[str] = getattr(request.app.state, "database_init_error", None)
    if init_err:
        raise HTTPException(status_code=503, detail=init_err)
    pool = get_pool_from_app(request)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="数据库未配置：请设置环境变量 DATABASE_URL",
        )
    yield pool
