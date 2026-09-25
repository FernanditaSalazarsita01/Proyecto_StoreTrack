from __future__ import annotations

from typing import Any
from .customer_features import build_current_customer_features
from .model_manager import load_model


def probability_level(probability: float) -> str:
    if probability >= 0.70:
        return "Alta"
    if probability >= 0.40:
        return "Media"
    return "Baja"


def predict_company_customers(database, company_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    package = load_model(company_id)
    model = package["model"]
    feature_columns = package["feature_columns"]
    dataframe = build_current_customer_features(database, company_id)
    if dataframe.empty:
        return [], package
    X = dataframe[feature_columns].astype(float)
    probabilities = model.predict_proba(X)[:, 1]
    results = []
    for (_, row), probability in zip(dataframe.iterrows(), probabilities):
        value = float(probability)
        results.append({
            "client_id": row["client_id"],
            "client_name": row["client_name"],
            "last_purchase_at": row["last_purchase_at"],
            "purchase_count": int(row["purchase_count"]),
            "total_spent": round(float(row["total_spent"]), 2),
            "avg_purchase": round(float(row["avg_purchase"]), 2),
            "days_since_last_purchase": int(row["days_since_last_purchase"]),
            "probability": round(value * 100, 2),
            "level": probability_level(value),
        })
    results.sort(key=lambda item: item["probability"], reverse=True)
    return results, package
