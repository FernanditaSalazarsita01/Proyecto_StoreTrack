from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

DEFAULT_CREDIT_DAYS = 30


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def get_credit_summary(db, company_id: str, credit_days: int = DEFAULT_CREDIT_DAYS) -> dict:
    now = datetime.utcnow()
    sales = list(db["sales"].find({"company_id": company_id, "sale_type": "credit"}))

    total_credit = sum(_number(sale.get("total")) for sale in sales)
    pending_balance = sum(_number(sale.get("balance")) for sale in sales)
    overdue_balance = 0.0
    overdue_sales = 0
    debtors: set[str] = set()
    overdue_customers: set[str] = set()

    for sale in sales:
        balance = _number(sale.get("balance"))
        customer_name = str((sale.get("customer", {}) or {}).get("name") or "Cliente")
        if balance > 0:
            debtors.add(customer_name)

        created_at = sale.get("created_at")
        due_date = sale.get("due_date")
        if not isinstance(due_date, datetime) and isinstance(created_at, datetime):
            due_date = created_at + timedelta(days=credit_days)

        if balance > 0 and isinstance(due_date, datetime) and due_date < now:
            overdue_balance += balance
            overdue_sales += 1
            overdue_customers.add(customer_name)

    return {
        "total_credit": round(total_credit, 2),
        "pending_balance": round(pending_balance, 2),
        "overdue_balance": round(overdue_balance, 2),
        "credit_sales": len(sales),
        "pending_customers": len(debtors),
        "overdue_customers": len(overdue_customers),
        "overdue_sales": overdue_sales,
        "credit_days": credit_days,
    }


def get_overdue_customers(
    db,
    company_id: str,
    credit_days: int = DEFAULT_CREDIT_DAYS,
    limit: int = 20,
) -> list[dict]:
    now = datetime.utcnow()
    sales = db["sales"].find({
        "company_id": company_id,
        "sale_type": "credit",
        "balance": {"$gt": 0},
    })
    grouped: dict[str, dict] = defaultdict(lambda: {
        "name": "Cliente",
        "balance": 0.0,
        "overdue_sales": 0,
        "max_days_overdue": 0,
        "oldest_due_date": None,
    })

    for sale in sales:
        created_at = sale.get("created_at")
        due_date = sale.get("due_date")
        if not isinstance(due_date, datetime) and isinstance(created_at, datetime):
            due_date = created_at + timedelta(days=credit_days)
        if not isinstance(due_date, datetime) or due_date >= now:
            continue

        customer = sale.get("customer", {}) or {}
        key = str(customer.get("client_id") or customer.get("name") or sale.get("_id"))
        row = grouped[key]
        row["name"] = str(customer.get("name") or "Cliente")
        row["balance"] += _number(sale.get("balance"))
        row["overdue_sales"] += 1
        days_overdue = (now - due_date).days
        row["max_days_overdue"] = max(row["max_days_overdue"], days_overdue)
        if row["oldest_due_date"] is None or due_date < row["oldest_due_date"]:
            row["oldest_due_date"] = due_date

    results: list[dict] = []
    for row in grouped.values():
        days = row["max_days_overdue"]
        risk = "Crítico" if days > 60 else "Alto" if days > 30 else "Medio"
        results.append({
            **row,
            "balance": round(row["balance"], 2),
            "risk": risk,
        })

    results.sort(key=lambda item: (item["max_days_overdue"], item["balance"]), reverse=True)
    return results[:limit]
