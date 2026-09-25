from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


def _sales_since(db, company_id: str, days: int | None = None) -> list[dict]:
    query: dict[str, Any] = {"company_id": company_id}
    if days is not None:
        query["created_at"] = {"$gte": datetime.utcnow() - timedelta(days=days)}
    return list(db["sales"].find(query))


def product_sales_metrics(db, company_id: str, days: int | None = None) -> dict[str, dict]:
    metrics: dict[str, dict] = defaultdict(lambda: {
        "product_id": "", "name": "Producto sin nombre", "sku": "", "units_sold": 0,
        "revenue": 0.0, "sales_count": 0, "last_sale": None,
    })
    for sale in _sales_since(db, company_id, days):
        sale_date = sale.get("created_at")
        seen: set[str] = set()
        for item in sale.get("items", []) or []:
            key = str(item.get("product_id") or item.get("sku") or item.get("name") or "")
            if not key:
                continue
            row = metrics[key]
            row["product_id"] = str(item.get("product_id") or "")
            row["name"] = str(item.get("name") or "Producto sin nombre")
            row["sku"] = str(item.get("sku") or "")
            qty = _integer(item.get("qty"))
            row["units_sold"] += qty
            row["revenue"] += _number(item.get("line_total"), _number(item.get("price")) * qty)
            if key not in seen:
                row["sales_count"] += 1
                seen.add(key)
            if isinstance(sale_date, datetime) and (row["last_sale"] is None or sale_date > row["last_sale"]):
                row["last_sale"] = sale_date
    return dict(metrics)


def get_top_products(db, company_id: str, days: int = 30, limit: int = 5) -> list[dict]:
    rows = list(product_sales_metrics(db, company_id, days).values())
    rows.sort(key=lambda x: (x["units_sold"], x["revenue"]), reverse=True)
    return rows[:limit]


def get_top_revenue_products(db, company_id: str, days: int = 30, limit: int = 5) -> list[dict]:
    rows = list(product_sales_metrics(db, company_id, days).values())
    rows.sort(key=lambda x: x["revenue"], reverse=True)
    return rows[:limit]


def get_least_sold_products(db, company_id: str, days: int = 30, limit: int = 5) -> list[dict]:
    products = list(db["products"].find({"company_id": company_id}))
    metrics = product_sales_metrics(db, company_id, days)
    rows = []
    for p in products:
        pid = str(p.get("_id"))
        m = metrics.get(pid, {})
        rows.append({
            "product_id": pid, "name": p.get("name", "Producto sin nombre"), "sku": p.get("sku", ""),
            "stock": _integer(p.get("stock")), "units_sold": _integer(m.get("units_sold")),
            "revenue": round(_number(m.get("revenue")), 2),
        })
    rows.sort(key=lambda x: (x["units_sold"], x["revenue"], -x["stock"]))
    return rows[:limit]


def get_low_stock_products(db, company_id: str, stock_threshold: int = 10, sales_window_days: int = 30,
                           coverage_warning_days: int = 15, limit: int = 50) -> list[dict]:
    products = list(db["products"].find({"company_id": company_id}))
    recent = product_sales_metrics(db, company_id, sales_window_days)
    results = []
    for product in products:
        pid = str(product.get("_id"))
        stock = _integer(product.get("stock"))
        sales = recent.get(pid, {})
        units = _integer(sales.get("units_sold"))
        avg_daily = units / max(sales_window_days, 1)
        coverage = round(stock / avg_daily, 1) if avg_daily > 0 else None
        if not (stock <= stock_threshold or (coverage is not None and coverage <= coverage_warning_days)):
            continue
        if stock <= 0 or (coverage is not None and coverage <= 7):
            risk, order = "Crítico", 0
        elif stock <= stock_threshold or (coverage is not None and coverage <= coverage_warning_days):
            risk, order = "Alto", 1
        else:
            risk, order = "Medio", 2
        suggested = max(0, int(round(avg_daily * 30 - stock)))
        results.append({
            "product_id": pid, "name": product.get("name", "Producto sin nombre"), "sku": product.get("sku", ""),
            "category": product.get("category", "Sin categoría"), "stock": stock, "units_30d": units,
            "avg_daily": round(avg_daily, 2), "coverage_days": coverage, "risk": risk,
            "risk_order": order, "suggested_purchase": suggested,
        })
    results.sort(key=lambda x: (x["risk_order"], x["coverage_days"] if x["coverage_days"] is not None else 999999, x["stock"]))
    return results[:limit]


def get_first_to_run_out(db, company_id: str, limit: int = 5) -> list[dict]:
    rows = [x for x in get_low_stock_products(db, company_id, limit=100) if x["coverage_days"] is not None]
    rows.sort(key=lambda x: (x["coverage_days"], x["stock"]))
    return rows[:limit]


def get_slow_moving_products(db, company_id: str, inactive_days: int = 60, limit: int = 20) -> list[dict]:
    now = datetime.utcnow()
    all_metrics = product_sales_metrics(db, company_id, None)
    products = list(db["products"].find({"company_id": company_id}))
    results = []
    for product in products:
        pid = str(product.get("_id"))
        metric = all_metrics.get(pid, {})
        last_sale = metric.get("last_sale")
        days_without = (now - last_sale).days if isinstance(last_sale, datetime) else None
        if last_sale is not None and days_without < inactive_days:
            continue
        stock = _integer(product.get("stock"))
        price = _number(product.get("price"))
        results.append({
            "product_id": pid, "name": product.get("name", "Producto sin nombre"), "sku": product.get("sku", ""),
            "category": product.get("category", "Sin categoría"), "stock": stock, "last_sale": last_sale,
            "days_without_sale": days_without, "inventory_value": round(stock * price, 2),
            "has_never_sold": last_sale is None,
        })
    results.sort(key=lambda x: (x["has_never_sold"], x["days_without_sale"] or 999999, x["inventory_value"]), reverse=True)
    return results[:limit]


def get_overstock_products(db, company_id: str, days: int = 30, coverage_days: int = 90, limit: int = 20) -> list[dict]:
    products = list(db["products"].find({"company_id": company_id}))
    metrics = product_sales_metrics(db, company_id, days)
    results = []
    for p in products:
        pid = str(p.get("_id"))
        stock = _integer(p.get("stock"))
        price = _number(p.get("price"))
        units = _integer(metrics.get(pid, {}).get("units_sold"))
        avg_daily = units / max(days, 1)
        coverage = round(stock / avg_daily, 1) if avg_daily > 0 else None
        if stock <= 0:
            continue
        if coverage is None or coverage >= coverage_days:
            results.append({
                "product_id": pid, "name": p.get("name", "Producto sin nombre"), "sku": p.get("sku", ""),
                "stock": stock, "units_30d": units, "coverage_days": coverage,
                "inventory_value": round(stock * price, 2),
            })
    results.sort(key=lambda x: (x["coverage_days"] is None, x["coverage_days"] or 999999, x["inventory_value"]), reverse=True)
    return results[:limit]


def get_restock_recommendations(db, company_id: str, limit: int = 20) -> list[dict]:
    rows = [x for x in get_low_stock_products(db, company_id, limit=100) if x["suggested_purchase"] > 0]
    return rows[:limit]


def get_product_trends(db, company_id: str, direction: str = "up", limit: int = 10) -> list[dict]:
    now = datetime.utcnow()
    current_start = now - timedelta(days=30)
    previous_start = now - timedelta(days=60)
    current = product_sales_metrics(db, company_id, 30)
    previous_sales = list(db["sales"].find({"company_id": company_id, "created_at": {"$gte": previous_start, "$lt": current_start}}))
    previous: dict[str, dict] = defaultdict(lambda: {"name": "Producto", "units_sold": 0, "revenue": 0.0})
    for sale in previous_sales:
        for item in sale.get("items", []) or []:
            key = str(item.get("product_id") or item.get("sku") or item.get("name") or "")
            if not key:
                continue
            qty = _integer(item.get("qty"))
            previous[key]["name"] = str(item.get("name") or "Producto")
            previous[key]["units_sold"] += qty
            previous[key]["revenue"] += _number(item.get("line_total"), _number(item.get("price")) * qty)
    keys = set(current) | set(previous)
    rows = []
    for key in keys:
        cur = current.get(key, {})
        prev = previous.get(key, {})
        current_units = _integer(cur.get("units_sold"))
        previous_units = _integer(prev.get("units_sold"))
        change = current_units - previous_units
        pct = round((change / previous_units) * 100, 1) if previous_units > 0 else (100.0 if current_units > 0 else 0.0)
        row = {"name": cur.get("name") or prev.get("name") or "Producto", "current_units": current_units,
               "previous_units": previous_units, "change_units": change, "change_percent": pct}
        if (direction == "up" and change > 0) or (direction == "down" and change < 0):
            rows.append(row)
    rows.sort(key=lambda x: abs(x["change_units"]), reverse=True)
    return rows[:limit]
