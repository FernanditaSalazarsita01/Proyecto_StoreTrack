from __future__ import annotations

from datetime import datetime, timedelta

from .credits import get_credit_summary, get_overdue_customers
from .customers import get_top_customers
from .products import (
    get_low_stock_products,
    get_slow_moving_products,
    get_top_products,
    get_top_revenue_products,
)


def build_dashboard(db, company_id: str) -> dict:
    now = datetime.utcnow()
    start_month = datetime(now.year, now.month, 1)

    month_sales = list(db["sales"].find({
        "company_id": company_id,
        "created_at": {"$gte": start_month},
    }))
    month_revenue = round(sum(float(sale.get("total", 0) or 0) for sale in month_sales), 2)

    low_stock = get_low_stock_products(db, company_id, limit=10)
    slow_products = get_slow_moving_products(db, company_id, inactive_days=60, limit=10)
    top_products = get_top_products(db, company_id, days=30, limit=5)
    top_revenue = get_top_revenue_products(db, company_id, days=30, limit=5)
    top_customers = get_top_customers(db, company_id, days=30, limit=5)
    credit_summary = get_credit_summary(db, company_id)
    overdue_customers = get_overdue_customers(db, company_id, limit=5)

    alerts: list[dict] = []
    if low_stock:
        alerts.append({
            "type": "danger",
            "title": "Inventario en riesgo",
            "message": f"Hay {len(low_stock)} productos con stock bajo o poca cobertura.",
        })
    if slow_products:
        alerts.append({
            "type": "warning",
            "title": "Productos sin movimiento",
            "message": f"Hay {len(slow_products)} productos sin ventas recientes.",
        })
    if credit_summary["overdue_customers"]:
        alerts.append({
            "type": "danger",
            "title": "Cobranza pendiente",
            "message": f"Hay {credit_summary['overdue_customers']} clientes con saldo vencido.",
        })
    if not alerts:
        alerts.append({
            "type": "success",
            "title": "Operación estable",
            "message": "No se detectaron alertas importantes con las reglas actuales.",
        })

    return {
        "generated_at": now,
        "kpis": {
            "month_sales": len(month_sales),
            "month_revenue": month_revenue,
            "low_stock": len(low_stock),
            "slow_products": len(slow_products),
            "overdue_customers": credit_summary["overdue_customers"],
            "alerts": len([alert for alert in alerts if alert["type"] != "success"]),
        },
        "alerts": alerts,
        "low_stock": low_stock,
        "slow_products": slow_products,
        "top_products": top_products,
        "top_revenue": top_revenue,
        "top_customers": top_customers,
        "credit_summary": credit_summary,
        "overdue_customers": overdue_customers,
    }
