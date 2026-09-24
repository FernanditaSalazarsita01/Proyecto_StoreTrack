from __future__ import annotations

from datetime import datetime
from typing import Any
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from .customer_features import FEATURE_COLUMNS, TARGET_COLUMN, build_training_dataset
from .model_manager import save_model

# Mínimos reducidos para que el módulo funcione como demostración con pocos datos.
MIN_TRAINING_ROWS = 4
MIN_ROWS_PER_CLASS = 1
MIN_CUSTOMERS = 2


class TrainingDataError(ValueError):
    pass


def validate_training_data(dataframe) -> dict[int, int]:
    if len(dataframe) < MIN_TRAINING_ROWS:
        raise TrainingDataError(
            f"Se requieren al menos {MIN_TRAINING_ROWS} ejemplos. Actualmente existen {len(dataframe)}."
        )
    customer_count = dataframe["client_id"].nunique()
    if customer_count < MIN_CUSTOMERS:
        raise TrainingDataError(
            f"Se requieren al menos {MIN_CUSTOMERS} clientes con ventas. Actualmente existe(n) {customer_count}."
        )
    class_counts = dataframe[TARGET_COLUMN].value_counts().to_dict()
    if len(class_counts) < 2:
        raise TrainingDataError(
            "Se necesita al menos un caso de recompra y uno de no recompra. "
            "Registra dos o más ventas para algún cliente y al menos una venta para otro cliente."
        )
    return {int(key): int(value) for key, value in class_counts.items()}


def train_company_model(database, company_id: str, company_name: str = "") -> dict[str, Any]:
    dataframe = build_training_dataset(database, company_id)
    class_counts = validate_training_data(dataframe)
    X = dataframe[FEATURE_COLUMNS].astype(float)
    y = dataframe[TARGET_COLUMN].astype(int)

    # Para conjuntos pequeños usamos una separación estratificada por fila.
    # Esto permite ejecutar la demostración sin exigir decenas de clientes.
    smallest_class = int(y.value_counts().min())
    can_holdout = len(dataframe) >= 8 and smallest_class >= 2

    if can_holdout:
        test_size = max(2, int(round(len(dataframe) * 0.25)))
        test_size = min(test_size, len(dataframe) - 2)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )
    else:
        # En modo demostración, cuando aún hay muy pocos registros, se entrena y
        # evalúa con todos los datos. La interfaz identifica esta modalidad.
        X_train, X_test, y_train, y_test = X, X, y, y

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        min_samples_split=2,
        min_samples_leaf=1,
        max_features="sqrt",
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)
    probabilities = model.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy": round(float(accuracy_score(y_test, predictions)), 4),
        "precision": round(float(precision_score(y_test, predictions, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, predictions, zero_division=0)), 4),
        "f1": round(float(f1_score(y_test, predictions, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, probabilities)), 4) if y_test.nunique() == 2 else 0.0,
    }
    feature_importance = sorted(
        [
            {"feature": feature, "importance": round(float(importance), 6)}
            for feature, importance in zip(FEATURE_COLUMNS, model.feature_importances_)
        ],
        key=lambda item: item["importance"],
        reverse=True,
    )
    package = {
        "model": model,
        "company_id": str(company_id),
        "company_name": company_name,
        "feature_columns": FEATURE_COLUMNS,
        "target_column": TARGET_COLUMN,
        "prediction_window_days": None,
        "trained_at": datetime.utcnow(),
        "training_rows": int(len(dataframe)),
        "training_customers": int(dataframe["client_id"].nunique()),
        "class_counts": class_counts,
        "metrics": metrics,
        "feature_importance": feature_importance,
        "evaluation_mode": "stratified_holdout" if can_holdout else "demo_training_data",
    }
    path = save_model(company_id, package)
    return {**package, "model": None, "model_path": str(path)}
