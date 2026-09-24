from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _range(period: str) -> tuple[datetime, datetime]:
    now = datetime.utcnow()
    if period == "today":
        start = datetime(now.year, now.month, now.day)
    elif period == "week":
        start = datetime(now.year, now.month, now.day) - timedelta(days=now.weekday())
    elif period == "year":
        start = datetime(now.year, 1, 1)
    else:
        start = datetime(now.year, now.month, 1)
    return start, now


def get_sales_period_summary(db, company_id: str, period: str = "month") -> dict:
    start, end = _range(period)
    sales = list(db["sales"].find({"company_id": company_id, "created_at": {"$gte": start, "$lte": end}}))
    total = sum(_number(s.get("total")) for s in sales)
    return {"period": period, "sales_count": len(sales), "revenue": round(total, 2), "avg_ticket": round(total / len(sales), 2) if sales else 0}


def get_largest_sale(db, company_id: str, period: str = "month") -> dict | None:
    start, end = _range(period)
    sale = db["sales"].find_one({"company_id": company_id, "created_at": {"$gte": start, "$lte": end}}, sort=[("total", -1)])
    if not sale:
        return None
    customer = sale.get("customer", {}) or {}
    return {"customer_name": customer.get("name", "Venta rápida"), "total": _number(sale.get("total")), "created_at": sale.get("created_at"), "sale_type": sale.get("sale_type", "cash")}


def get_best_sales_day(db, company_id: str, days: int = 90) -> dict | None:
    since = datetime.utcnow() - timedelta(days=days)
    grouped = defaultdict(lambda: {"sales_count": 0, "revenue": 0.0})
    for sale in db["sales"].find({"company_id": company_id, "created_at": {"$gte": since}}):
        date = sale.get("created_at")
        if not isinstance(date, datetime):
            continue
        key = date.strftime("%Y-%m-%d")
        grouped[key]["sales_count"] += 1
        grouped[key]["revenue"] += _number(sale.get("total"))
    if not grouped:
        return None
    date, row = max(grouped.items(), key=lambda x: (x[1]["revenue"], x[1]["sales_count"]))
    return {"date": date, "sales_count": row["sales_count"], "revenue": round(row["revenue"], 2)}


def get_payment_mix(db, company_id: str, period: str = "month") -> dict:
    start, end = _range(period)
    result = {"cash_sales": 0, "cash_revenue": 0.0, "credit_sales": 0, "credit_revenue": 0.0}
    for sale in db["sales"].find({"company_id": company_id, "created_at": {"$gte": start, "$lte": end}}):
        if sale.get("sale_type") == "credit":
            result["credit_sales"] += 1
            result["credit_revenue"] += _number(sale.get("total"))
        else:
            result["cash_sales"] += 1
            result["cash_revenue"] += _number(sale.get("total"))
    result["cash_revenue"] = round(result["cash_revenue"], 2)
    result["credit_revenue"] = round(result["credit_revenue"], 2)
    return result
