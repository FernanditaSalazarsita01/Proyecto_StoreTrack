from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def customer_key(sale: dict) -> str:
    customer = sale.get("customer", {}) or {}
    cid = str(customer.get("client_id") or "").strip()
    if cid:
        return f"id:{cid}"
    name = str(customer.get("name") or "").strip()
    if name and name.lower() != "venta rápida":
        return f"name:{name.lower()}"
    return ""


def get_customer_metrics(db, company_id: str, days: int | None = None) -> list[dict]:
    query: dict[str, Any] = {"company_id": company_id}
    if days is not None:
        query["created_at"] = {"$gte": datetime.utcnow() - timedelta(days=days)}
    sales = db["sales"].find(query)
    grouped: dict[str, dict] = defaultdict(lambda: {
        "client_id": "", "name": "Cliente", "purchases": 0, "total_spent": 0.0, "units": 0,
        "last_purchase": None, "first_purchase": None, "cash_sales": 0, "credit_sales": 0,
        "product_counter": Counter(), "category_counter": Counter(),
    })
    products_by_id = {str(p["_id"]): p for p in db["products"].find({"company_id": company_id})}
    for sale in sales:
        key = customer_key(sale)
        if not key:
            continue
        customer = sale.get("customer", {}) or {}
        row = grouped[key]
        row["client_id"] = str(customer.get("client_id") or "")
        row["name"] = str(customer.get("name") or "Cliente")
        row["purchases"] += 1
        row["total_spent"] += _number(sale.get("total"))
        sale_date = sale.get("created_at")
        if isinstance(sale_date, datetime):
            row["last_purchase"] = max(row["last_purchase"], sale_date) if row["last_purchase"] else sale_date
            row["first_purchase"] = min(row["first_purchase"], sale_date) if row["first_purchase"] else sale_date
        if sale.get("sale_type") == "credit":
            row["credit_sales"] += 1
        else:
            row["cash_sales"] += 1
        for item in sale.get("items", []) or []:
            qty = _integer(item.get("qty"))
            name = str(item.get("name") or "Producto")
            row["units"] += qty
            row["product_counter"][name] += qty
            product = products_by_id.get(str(item.get("product_id") or ""), {})
            row["category_counter"][str(product.get("category") or "Sin categoría")] += qty
    results = []
    now = datetime.utcnow()
    for row in grouped.values():
        purchases = row["purchases"]
        pref_product = row["product_counter"].most_common(1)
        pref_category = row["category_counter"].most_common(1)
        span_days = max((row["last_purchase"] - row["first_purchase"]).days, 1) if row["last_purchase"] and row["first_purchase"] else 1
        frequency_days = round(span_days / max(purchases - 1, 1), 1) if purchases > 1 else None
        results.append({
            "client_id": row["client_id"], "name": row["name"], "purchases": purchases,
            "total_spent": round(row["total_spent"], 2), "avg_ticket": round(row["total_spent"] / purchases, 2) if purchases else 0,
            "units": row["units"], "last_purchase": row["last_purchase"],
            "days_since_last_purchase": (now - row["last_purchase"]).days if row["last_purchase"] else None,
            "purchase_frequency_days": frequency_days,
            "preferred_product": pref_product[0][0] if pref_product else "Sin información",
            "preferred_category": pref_category[0][0] if pref_category else "Sin información",
            "payment_preference": "Crédito" if row["credit_sales"] > row["cash_sales"] else "Contado",
            "credit_sales": row["credit_sales"], "cash_sales": row["cash_sales"],
        })
    return results


def get_top_customers(db, company_id: str, days: int = 30, limit: int = 10, sort_by: str = "total_spent") -> list[dict]:
    rows = get_customer_metrics(db, company_id, days)
    if sort_by == "purchases":
        rows.sort(key=lambda x: (x["purchases"], x["total_spent"]), reverse=True)
    elif sort_by == "avg_ticket":
        rows.sort(key=lambda x: (x["avg_ticket"], x["total_spent"]), reverse=True)
    elif sort_by == "frequency":
        rows = [x for x in rows if x["purchase_frequency_days"] is not None]
        rows.sort(key=lambda x: (x["purchase_frequency_days"], -x["purchases"]))
    else:
        rows.sort(key=lambda x: (x["total_spent"], x["purchases"]), reverse=True)
    return rows[:limit]


def get_inactive_customers(db, company_id: str, inactive_days: int = 60, limit: int = 20) -> list[dict]:
    rows = [x for x in get_customer_metrics(db, company_id, None) if (x["days_since_last_purchase"] or 0) >= inactive_days]
    rows.sort(key=lambda x: (x["days_since_last_purchase"], x["total_spent"]), reverse=True)
    return rows[:limit]


def get_credit_preference_customers(db, company_id: str, limit: int = 20) -> list[dict]:
    rows = [x for x in get_customer_metrics(db, company_id, None) if x["credit_sales"] > x["cash_sales"]]
    rows.sort(key=lambda x: (x["credit_sales"], x["total_spent"]), reverse=True)
    return rows[:limit]


def get_preferred_products_by_customer(db, company_id: str, limit: int = 20) -> list[dict]:
    rows = get_customer_metrics(db, company_id, None)
    rows.sort(key=lambda x: x["total_spent"], reverse=True)
    return rows[:limit]


def get_customer_purchase_profile(db, company_id: str, customer_name: str) -> dict | None:
    normalized = customer_name.strip()
    if not normalized:
        return None
    sales = list(db["sales"].find({"company_id": company_id, "customer.name": {"$regex": f"^{re_escape(normalized)}$", "$options": "i"}}).sort("created_at", -1))
    if not sales:
        sales = list(db["sales"].find({"company_id": company_id, "customer.name": {"$regex": re_escape(normalized), "$options": "i"}}).sort("created_at", -1))
    if not sales:
        return None
    product_counter: Counter = Counter()
    total = 0.0
    credit_sales = 0
    pending_balance = 0.0
    for sale in sales:
        total += _number(sale.get("total"))
        if sale.get("sale_type") == "credit":
            credit_sales += 1
            pending_balance += _number(sale.get("balance"))
        for item in sale.get("items", []) or []:
            product_counter[str(item.get("name") or "Producto")] += _integer(item.get("qty"))
    return {
        "name": (sales[0].get("customer", {}) or {}).get("name", customer_name), "purchases": len(sales),
        "total_spent": round(total, 2), "avg_ticket": round(total / len(sales), 2), "credit_sales": credit_sales,
        "pending_balance": round(pending_balance, 2), "last_purchase": sales[0].get("created_at"),
        "top_products": [{"name": name, "units": units} for name, units in product_counter.most_common(5)],
    }


def re_escape(value: str) -> str:
    import re
    return re.escape(value)
