from __future__ import annotations

from datetime import datetime
from itertools import product
from typing import Any

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GroupShuffleSplit

from helpers.machine_learning.customer_features import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    build_training_dataset,
)
from helpers.machine_learning.model_manager import save_model
from helpers.machine_learning.train_model import TrainingDataError


def run_trial_error_search(
    database,
    company_id: str,
    company_name: str = "",
) -> dict[str, Any]:
    """
    Prueba varias configuraciones de Random Forest y guarda
    automáticamente la que obtenga el mejor F1.

    Este proceso representa un algoritmo sistemático
    de prueba y error.
    """

    dataframe = build_training_dataset(
        database,
        company_id,
    )

    if dataframe.empty:
        raise TrainingDataError(
            "No existen ejemplos históricos para ejecutar las pruebas."
        )

    if len(dataframe) < 10:
        raise TrainingDataError(
            "Se requieren al menos 10 ejemplos para ejecutar "
            "una prueba y error básica."
        )

    if dataframe[TARGET_COLUMN].nunique() < 2:
        raise TrainingDataError(
            "Deben existir casos de recompra y no recompra."
        )

    if dataframe["client_id"].nunique() < 2:
        raise TrainingDataError(
            "Se requieren al menos dos clientes con historial."
        )

    X = dataframe[FEATURE_COLUMNS].astype(float)
    y = dataframe[TARGET_COLUMN].astype(int)
    groups = dataframe["client_id"].astype(str)

    splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=0.25,
        random_state=42,
    )

    train_indexes, test_indexes = next(
        splitter.split(
            X,
            y,
            groups=groups,
        )
    )

    X_train = X.iloc[train_indexes]
    X_test = X.iloc[test_indexes]

    y_train = y.iloc[train_indexes]
    y_test = y.iloc[test_indexes]

    if y_train.nunique() < 2:
        raise TrainingDataError(
            "El conjunto de entrenamiento no contiene ambas clases."
        )

    # Configuraciones que el sistema probará.
    search_space = {
        "n_estimators": [50, 100, 200, 300],
        "max_depth": [4, 8, 12, None],
        "min_samples_leaf": [1, 2, 4],
        "max_features": ["sqrt", "log2"],
    }

    combinations = product(
        search_space["n_estimators"],
        search_space["max_depth"],
        search_space["min_samples_leaf"],
        search_space["max_features"],
    )

    trials = []
    best_model = None
    best_result = None

    for trial_number, combination in enumerate(
        combinations,
        start=1,
    ):
        (
            n_estimators,
            max_depth,
            min_samples_leaf,
            max_features,
        ) = combination

        model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            min_samples_split=2,
            max_features=max_features,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )

        model.fit(
            X_train,
            y_train,
        )

        predictions = model.predict(
            X_test
        )

        accuracy = float(
            accuracy_score(
                y_test,
                predictions,
            )
        )

        precision = float(
            precision_score(
                y_test,
                predictions,
                zero_division=0,
            )
        )

        recall = float(
            recall_score(
                y_test,
                predictions,
                zero_division=0,
            )
        )

        f1 = float(
            f1_score(
                y_test,
                predictions,
                zero_division=0,
            )
        )

        trial_result = {
            "trial": trial_number,
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "min_samples_leaf": min_samples_leaf,
            "max_features": max_features,
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

        trials.append(
            trial_result
        )

        if (
            best_result is None
            or f1 > best_result["f1"]
            or (
                f1 == best_result["f1"]
                and accuracy > best_result["accuracy"]
            )
        ):
            best_model = model
            best_result = trial_result

    feature_importance = sorted(
        [
            {
                "feature": feature,
                "importance": round(
                    float(importance),
                    6,
                ),
            }
            for feature, importance in zip(
                FEATURE_COLUMNS,
                best_model.feature_importances_,
            )
        ],
        key=lambda item: item["importance"],
        reverse=True,
    )

    package = {
        "model": best_model,
        "company_id": str(company_id),
        "company_name": company_name,
        "feature_columns": FEATURE_COLUMNS,
        "target_column": TARGET_COLUMN,
        "prediction_window_days": 30,
        "trained_at": datetime.utcnow(),
        "training_rows": int(
            len(dataframe)
        ),
        "training_customers": int(
            dataframe["client_id"].nunique()
        ),
        "metrics": {
            "accuracy": best_result["accuracy"],
            "precision": best_result["precision"],
            "recall": best_result["recall"],
            "f1": best_result["f1"],
            "roc_auc": None,
        },
        "feature_importance": feature_importance,
        "selected_parameters": {
            "n_estimators": best_result["n_estimators"],
            "max_depth": best_result["max_depth"],
            "min_samples_leaf": best_result[
                "min_samples_leaf"
            ],
            "max_features": best_result[
                "max_features"
            ],
        },
        "training_method": "trial_error",
        "total_trials": len(trials),
    }

    save_model(
        company_id,
        package,
    )

    trials.sort(
        key=lambda item: (
            item["f1"],
            item["accuracy"],
        ),
        reverse=True,
    )

    return {
        "best": best_result,
        "trials": trials,
        "total_trials": len(trials),
        "training_rows": len(dataframe),
        "training_customers": dataframe[
            "client_id"
        ].nunique(),
    }