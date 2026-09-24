from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Iterable
import pandas as pd

FEATURE_COLUMNS = [
    "purchase_count", "total_spent", "avg_purchase",
    "days_since_last_purchase", "avg_days_between_purchases",
    "purchases_last_30_days", "purchases_last_90_days",
    "unique_products", "total_units", "credit_purchase_ratio",
]
# El objetivo ya no depende de una ventana fija de 30 días.
# 1 = el cliente volvió a comprar después de esa venta, sin importar cuántos días pasaron.
TARGET_COLUMN = "repurchased_later"


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def load_identified_company_sales(database, company_id: str) -> list[dict[str, Any]]:
    query = {
        "company_id": str(company_id),
        "customer.client_id": {"$exists": True, "$nin": [None, ""]},
        "created_at": {"$type": "date"},
    }
    return list(database["sales"].find(query).sort("created_at", 1))


def group_sales_by_customer(sales: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sale in sales:
        customer = sale.get("customer") or {}
        client_id = str(customer.get("client_id") or "").strip()
        created_at = sale.get("created_at")
        if client_id and isinstance(created_at, datetime):
            grouped[client_id].append(sale)
    for customer_sales in grouped.values():
        customer_sales.sort(key=lambda item: item["created_at"])
    return dict(grouped)


def _features_until(
    customer_sales: list[dict[str, Any]],
    reference_date: datetime,
    *,
    reference_is_purchase: bool = False,
) -> dict[str, float]:
    history = [
        sale for sale in customer_sales
        if isinstance(sale.get("created_at"), datetime)
        and sale["created_at"] <= reference_date
    ]
    if not history:
        raise ValueError("No existe historial antes de la fecha de referencia.")

    purchase_dates = [sale["created_at"] for sale in history]
    totals = [_safe_float(sale.get("total")) for sale in history]
    day_gaps = [
        max((purchase_dates[i] - purchase_dates[i - 1]).days, 0)
        for i in range(1, len(purchase_dates))
    ]
    cutoff_30 = reference_date - timedelta(days=30)
    cutoff_90 = reference_date - timedelta(days=90)

    product_ids: set[str] = set()
    total_units = 0
    for sale in history:
        for item in sale.get("items") or []:
            product_id = str(item.get("product_id") or item.get("sku") or "").strip()
            if product_id:
                product_ids.add(product_id)
            total_units += _safe_int(item.get("qty"))

    credit_purchases = sum(1 for sale in history if sale.get("sale_type") == "credit")
    purchase_count = len(history)
    total_spent = sum(totals)

    if reference_is_purchase:
        # En un ejemplo histórico la fecha de corte coincide con una compra.
        # Medimos los días transcurridos desde la compra anterior para evitar que siempre sea 0.
        days_since_last_purchase = (
            max((reference_date - purchase_dates[-2]).days, 0)
            if len(purchase_dates) >= 2
            else 0
        )
    else:
        # Para la predicción actual se mide desde la compra más reciente hasta hoy.
        days_since_last_purchase = max((reference_date - purchase_dates[-1]).days, 0)

    return {
        "purchase_count": float(purchase_count),
        "total_spent": round(total_spent, 2),
        "avg_purchase": round(total_spent / purchase_count, 2),
        "days_since_last_purchase": float(days_since_last_purchase),
        "avg_days_between_purchases": round(mean(day_gaps), 2) if day_gaps else 0.0,
        "purchases_last_30_days": float(sum(1 for date in purchase_dates if date >= cutoff_30)),
        "purchases_last_90_days": float(sum(1 for date in purchase_dates if date >= cutoff_90)),
        "unique_products": float(len(product_ids)),
        "total_units": float(total_units),
        "credit_purchase_ratio": round(credit_purchases / purchase_count, 4),
    }


def build_training_dataset(database, company_id: str) -> pd.DataFrame:
    """Genera un ejemplo por venta identificada, sin esperar una ventana de días.

    Para cada venta:
      - 1 si el mismo cliente tiene cualquier venta posterior.
      - 0 si esa es su venta más reciente.

    Así las ventas del mismo día o de cualquier antigüedad pueden utilizarse de inmediato.
    """
    sales = load_identified_company_sales(database, company_id)
    columns = FEATURE_COLUMNS + [
        "client_id", "client_name", "reference_date", TARGET_COLUMN
    ]
    if not sales:
        return pd.DataFrame(columns=columns)

    grouped = group_sales_by_customer(sales)
    client_docs = {
        str(client["_id"]): client
        for client in database["clients"].find({"company_id": str(company_id)})
    }
    rows: list[dict[str, Any]] = []

    for client_id, customer_sales in grouped.items():
        for index, sale in enumerate(customer_sales):
            reference_date = sale["created_at"]
            has_later_purchase = index + 1 < len(customer_sales)
            row = _features_until(
                customer_sales,
                reference_date,
                reference_is_purchase=True,
            )
            customer_snapshot = sale.get("customer") or {}
            client_doc = client_docs.get(client_id, {})
            client_name = (
                client_doc.get("name")
                or customer_snapshot.get("name")
                or "Cliente sin nombre"
            )
            row.update({
                "client_id": client_id,
                "client_name": client_name,
                "reference_date": reference_date,
                TARGET_COLUMN: int(has_later_purchase),
            })
            rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def build_current_customer_features(database, company_id: str, reference_date: datetime | None = None) -> pd.DataFrame:
    sales = load_identified_company_sales(database, company_id)
    grouped = group_sales_by_customer(sales)
    reference_date = reference_date or datetime.utcnow()
    client_docs = {
        str(client["_id"]): client
        for client in database["clients"].find({"company_id": str(company_id)})
    }
    columns = FEATURE_COLUMNS + ["client_id", "client_name", "last_purchase_at"]
    rows: list[dict[str, Any]] = []

    for client_id, customer_sales in grouped.items():
        last_sale = customer_sales[-1]
        customer_snapshot = last_sale.get("customer") or {}
        client_doc = client_docs.get(client_id, {})
        row = _features_until(customer_sales, reference_date)
        row.update({
            "client_id": client_id,
            "client_name": client_doc.get("name") or customer_snapshot.get("name") or "Cliente sin nombre",
            "last_purchase_at": last_sale.get("created_at"),
        })
        rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def get_company_clients_status(database, company_id: str) -> list[dict[str, Any]]:
    company_id = str(company_id)
    clients = list(database["clients"].find({"company_id": company_id}).sort("name", 1))
    pipeline = [
        {"$match": {
            "company_id": company_id,
            "customer.client_id": {"$exists": True, "$nin": [None, ""]},
        }},
        {"$group": {
            "_id": "$customer.client_id",
            "sales_count": {"$sum": 1},
            "total_spent": {"$sum": {"$convert": {"input": "$total", "to": "double", "onError": 0, "onNull": 0}}},
            "last_purchase_at": {"$max": "$created_at"},
        }},
    ]
    sales_by_client = {
        str(row["_id"]): row
        for row in database["sales"].aggregate(pipeline)
        if row.get("_id")
    }
    result = []
    for client in clients:
        client_id = str(client["_id"])
        sales_data = sales_by_client.get(client_id, {})
        sales_count = int(sales_data.get("sales_count", 0) or 0)
        total_spent = float(sales_data.get("total_spent", 0) or 0)
        result.append({
            "client_id": client_id,
            "client_name": client.get("name", "Cliente sin nombre"),
            "email": client.get("email", ""),
            "phone": client.get("phone", ""),
            "sales_count": sales_count,
            "total_spent": round(total_spent, 2),
            "last_purchase_at": sales_data.get("last_purchase_at"),
            "has_sales": sales_count > 0,
        })
    return result


def get_company_data_summary(database, company_id: str) -> dict[str, Any]:
    company_id = str(company_id)
    total_sales = database["sales"].count_documents({"company_id": company_id})
    identified_sales = database["sales"].count_documents({
        "company_id": company_id,
        "customer.client_id": {"$exists": True, "$nin": [None, ""]},
    })
    quick_sales = database["sales"].count_documents({
        "company_id": company_id,
        "$or": [
            {"customer.client_id": {"$exists": False}},
            {"customer.client_id": None},
            {"customer.client_id": ""},
        ],
    })
    registered_clients = database["clients"].count_documents({"company_id": company_id})
    identified = load_identified_company_sales(database, company_id)
    grouped = group_sales_by_customer(identified)
    training_df = build_training_dataset(database, company_id)
    class_counts = training_df[TARGET_COLUMN].value_counts().to_dict() if not training_df.empty else {}

    return {
        "total_sales": int(total_sales),
        "identified_sales": int(identified_sales),
        "quick_sales": int(quick_sales),
        "registered_clients": int(registered_clients),
        "customers_with_sales": int(len(grouped)),
        "clients_without_sales": max(int(registered_clients) - int(len(grouped)), 0),
        "training_rows": int(len(training_df)),
        "positive_rows": int(class_counts.get(1, 0)),
        "negative_rows": int(class_counts.get(0, 0)),
        "pending_evaluations": 0,
        "evaluable_sales": int(len(training_df)),
        "prediction_window_days": None,
    }