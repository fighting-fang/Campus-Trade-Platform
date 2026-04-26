from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import close_pool, create_and_open_pool, dns_precheck, get_db, validate_database_url
from app.settings import get_settings


BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.database_init_error = None
    app.state.db_pool = None
    if settings.database_url:
        url = settings.database_url
        msg = validate_database_url(url)
        if msg:
            logger.error("%s", msg)
            app.state.database_init_error = msg
        else:
            msg = await dns_precheck(url)
            if msg:
                logger.error("%s", msg)
                app.state.database_init_error = msg
            else:
                pool, err = await create_and_open_pool(url)
                if err:
                    logger.error("%s", err)
                    app.state.database_init_error = err
                else:
                    app.state.db_pool = pool
    yield
    await close_pool(getattr(app.state, "db_pool", None))


app = FastAPI(title="校园二手交易平台", lifespan=lifespan)


@dataclass(frozen=True)
class _QueryDef:
    """作业四·三～五：每条 SELECT 对应一个可书签的演示路由。"""

    query_id: str
    title: str
    section: str  # basic | join | agg
    sql: str


_QUERIES: Tuple[_QueryDef, ...] = (
    _QueryDef(
        "basic-unsold",
        "未售出商品（status = 0）",
        "basic",
        """
SELECT item_id, item_name, category, price, status, seller_id
FROM item
WHERE status = 0
ORDER BY item_id
        """.strip(),
    ),
    _QueryDef(
        "basic-price-over-30",
        "价格大于 30 的商品",
        "basic",
        """
SELECT item_id, item_name, category, price, status, seller_id
FROM item
WHERE price > 30
ORDER BY item_id
        """.strip(),
    ),
    _QueryDef(
        "basic-dailygoods",
        "「生活用品」类商品（种子数据字段为 DailyGoods）",
        "basic",
        """
SELECT item_id, item_name, category, price, status, seller_id
FROM item
WHERE category = 'DailyGoods'
ORDER BY item_id
        """.strip(),
    ),
    _QueryDef(
        "basic-seller-u001",
        "卖家 u001 发布的商品",
        "basic",
        """
SELECT item_id, item_name, category, price, status, seller_id
FROM item
WHERE seller_id = 'u001'
ORDER BY item_id
        """.strip(),
    ),
    _QueryDef(
        "join-sold-buyer-name",
        "已售商品及其买家姓名",
        "join",
        """
SELECT i.item_id, i.item_name, i.category, i.price,
       o.order_id, o.order_date, u.user_name AS buyer_name
FROM orders o
JOIN item i ON i.item_id = o.item_id
JOIN "User" u ON u.user_id = o.buyer_id
ORDER BY o.order_id
        """.strip(),
    ),
    _QueryDef(
        "join-order-item-buyer-date",
        "订单列表：商品名、买家名、下单日期",
        "join",
        """
SELECT o.order_id, i.item_name, u.user_name AS buyer_name, o.order_date
FROM orders o
JOIN item i ON i.item_id = o.item_id
JOIN "User" u ON u.user_id = o.buyer_id
ORDER BY o.order_id
        """.strip(),
    ),
    _QueryDef(
        "join-seller-u001-purchased",
        "卖家 u001 的每件商品是否已有订单（LEFT JOIN + 标志）",
        "join",
        """
SELECT i.item_id, i.item_name, i.status,
       CASE WHEN o.order_id IS NOT NULL THEN TRUE ELSE FALSE END AS has_order
FROM item i
LEFT JOIN orders o ON o.item_id = i.item_id
WHERE i.seller_id = 'u001'
ORDER BY i.item_id
        """.strip(),
    ),
    _QueryDef(
        "agg-total-items",
        "商品总数",
        "agg",
        "SELECT COUNT(*)::bigint AS total_items FROM item",
    ),
    _QueryDef(
        "agg-count-by-category",
        "按类别统计商品数量",
        "agg",
        """
SELECT category, COUNT(*)::bigint AS item_count
FROM item
GROUP BY category
ORDER BY category
        """.strip(),
    ),
    _QueryDef(
        "agg-avg-price",
        "全部商品的平均价格",
        "agg",
        "SELECT ROUND(AVG(price)::numeric, 2) AS avg_price_all_items FROM item",
    ),
    _QueryDef(
        "agg-top-seller-by-listings",
        "发布商品数量最多的用户",
        "agg",
        """
SELECT i.seller_id, u.user_name, COUNT(*)::bigint AS listing_count
FROM item i
JOIN "User" u ON u.user_id = i.seller_id
GROUP BY i.seller_id, u.user_name
ORDER BY COUNT(*) DESC, i.seller_id
LIMIT 1
        """.strip(),
    ),
)

_QUERY_BY_ID: Dict[str, _QueryDef] = {q.query_id: q for q in _QUERIES}


def _serialize_cell(value: Any) -> Any:
    """将驱动返回类型转为模板易读形式（避免 Decimal 等渲染歧义）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return value


async def _run_select(pool: Any, sql: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql)
            desc = cur.description or []
            columns = [d.name for d in desc]
            raw_rows = await cur.fetchall()
    rows: List[Dict[str, Any]] = []
    for tup in raw_rows:
        rows.append({c: _serialize_cell(v) for c, v in zip(columns, tup)})
    return columns, rows


def _redirect_items(request: Request, flash_ok: Optional[str] = None, flash_err: Optional[str] = None) -> RedirectResponse:
    base = str(request.url_for("page_items"))
    q: Dict[str, str] = {}
    if flash_ok:
        q["flash_ok"] = flash_ok
    if flash_err:
        q["flash_err"] = flash_err
    url = f"{base}?{urlencode(q)}" if q else base
    return RedirectResponse(url, status_code=303)


@app.get("/", response_class=HTMLResponse, name="page_home")
async def page_home(request: Request) -> Any:
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/items", response_class=HTMLResponse, name="page_items")
async def page_items(
    request: Request,
    flash_ok: Optional[str] = None,
    flash_err: Optional[str] = None,
    pool=Depends(get_db),
) -> Any:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT item_id, item_name, category, price, status, seller_id
                FROM item
                ORDER BY item_id
                """
            )
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in await cur.fetchall()]
            await cur.execute(
                """SELECT user_id, user_name, phone FROM "User" ORDER BY user_id"""
            )
            ucols = [d.name for d in cur.description]
            users = [dict(zip(ucols, r)) for r in await cur.fetchall()]
    return templates.TemplateResponse(
        request,
        "items.html",
        {
            "rows": rows,
            "users": users,
            "flash_ok": flash_ok,
            "flash_err": flash_err,
        },
    )


@app.get("/users", response_class=HTMLResponse, name="page_users")
async def page_users(request: Request, pool=Depends(get_db)) -> Any:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT user_id, user_name, phone FROM "User" ORDER BY user_id"""
            )
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in await cur.fetchall()]
    return templates.TemplateResponse(request, "users.html", {"rows": rows})


@app.get("/orders", response_class=HTMLResponse, name="page_orders")
async def page_orders(request: Request, pool=Depends(get_db)) -> Any:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT o.order_id, o.item_id, i.item_name, o.buyer_id, u.user_name AS buyer_name, o.order_date
                FROM orders o
                JOIN item i ON i.item_id = o.item_id
                JOIN "User" u ON u.user_id = o.buyer_id
                ORDER BY o.order_id
                """
            )
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in await cur.fetchall()]
    return templates.TemplateResponse(request, "orders.html", {"rows": rows})


@app.get("/queries", response_class=HTMLResponse, name="page_queries_hub")
async def page_queries_hub(request: Request) -> Any:
    def _links(section: str) -> List[Dict[str, str]]:
        return [{"id": q.query_id, "title": q.title} for q in _QUERIES if q.section == section]

    return templates.TemplateResponse(
        request,
        "query_hub.html",
        {
            "basic_queries": _links("basic"),
            "join_queries": _links("join"),
            "agg_queries": _links("agg"),
        },
    )


@app.get("/queries/{query_id}", response_class=HTMLResponse, name="page_query")
async def page_query(request: Request, query_id: str, pool=Depends(get_db)) -> Any:
    qdef = _QUERY_BY_ID.get(query_id)
    if qdef is None:
        raise HTTPException(status_code=404, detail="未知查询编号")
    columns, rows = await _run_select(pool, qdef.sql)
    return templates.TemplateResponse(
        request,
        "query_result.html",
        {
            "title": qdef.title,
            "sql": qdef.sql,
            "columns": columns,
            "rows": rows,
        },
    )


@app.post("/items/create", name="action_item_create")
async def action_item_create(
    request: Request,
    item_id: str = Form(...),
    item_name: str = Form(...),
    category: str = Form(...),
    price: str = Form(...),
    seller_id: str = Form(...),
    pool=Depends(get_db),
) -> RedirectResponse:
    try:
        price_dec = Decimal(price)
        if price_dec < 0:
            raise InvalidOperation()
    except (InvalidOperation, ValueError):
        return _redirect_items(request, flash_err="价格格式无效")
    async with pool.connection() as conn:
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO item (item_id, item_name, category, price, status, seller_id)
                    VALUES (%s, %s, %s, %s, 0, %s)
                    """,
                    (item_id.strip(), item_name.strip(), category.strip(), price_dec, seller_id.strip()),
                )
        except Exception as exc:  # noqa: BLE001 — 向用户展示数据库错误摘要
            return _redirect_items(request, flash_err=f"插入失败：{exc}")
    return _redirect_items(request, flash_ok="已插入新商品")


@app.post("/items/update-price", name="action_item_update_price")
async def action_item_update_price(
    request: Request,
    item_id: str = Form(...),
    price: str = Form(...),
    pool=Depends(get_db),
) -> RedirectResponse:
    try:
        price_dec = Decimal(price)
        if price_dec < 0:
            raise InvalidOperation()
    except (InvalidOperation, ValueError):
        return _redirect_items(request, flash_err="价格格式无效")
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE item SET price = %s WHERE item_id = %s",
                (price_dec, item_id.strip()),
            )
            if cur.rowcount == 0:
                return _redirect_items(request, flash_err="未找到该商品，价格未更新")
    return _redirect_items(request, flash_ok="已更新价格")


@app.post("/items/delete", name="action_item_delete")
async def action_item_delete(
    request: Request,
    item_id: str = Form(...),
    pool=Depends(get_db),
) -> RedirectResponse:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM item
                WHERE item_id = %s
                  AND status = 0
                  AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.item_id = item.item_id)
                """,
                (item_id.strip(),),
            )
            if cur.rowcount == 0:
                return _redirect_items(
                    request,
                    flash_err="删除失败：商品不存在、已售或已有订单引用",
                )
    return _redirect_items(request, flash_ok="已删除商品")


@app.post("/items/purchase", name="action_item_purchase")
async def action_item_purchase(
    request: Request,
    item_id: str = Form(...),
    buyer_id: str = Form(...),
    order_date: Optional[str] = Form(None),
    pool=Depends(get_db),
) -> RedirectResponse:
    item_id = item_id.strip()
    buyer_id = buyer_id.strip()
    if order_date:
        try:
            od = date.fromisoformat(order_date)
        except ValueError:
            return _redirect_items(request, flash_err="order_date 格式无效")
    else:
        od = date.today()

    order_id = ""
    async with pool.connection() as conn:
        try:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT status FROM item WHERE item_id = %s FOR UPDATE",
                        (item_id,),
                    )
                    row = await cur.fetchone()
                    if row is None:
                        raise ValueError("商品不存在")
                    if int(row[0]) != 0:
                        raise ValueError("商品已售，无法再次购买")

                    order_id = "o" + secrets.token_hex(4)
                    await cur.execute(
                        """
                        INSERT INTO orders (order_id, item_id, buyer_id, order_date)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (order_id, item_id, buyer_id, od),
                    )
                    await cur.execute(
                        "UPDATE item SET status = 1 WHERE item_id = %s",
                        (item_id,),
                    )
        except ValueError as exc:
            return _redirect_items(request, flash_err=str(exc))
        except Exception as exc:  # noqa: BLE001
            return _redirect_items(request, flash_err=f"购买失败：{exc}")

    return _redirect_items(request, flash_ok=f"购买成功，订单号 {order_id}")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/health/db")
async def health_db(pool=Depends(get_db)) -> dict:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
            row = await cur.fetchone()
    return {"status": "ok", "db": row[0] if row else None}
