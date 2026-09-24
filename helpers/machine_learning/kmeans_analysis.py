"""
Segmentación de clientes con K-Means.

Este módulo obtiene las características de compra de los clientes de una
empresa, calcula el método del codo con WCSS, selecciona un valor de K,
entrena K-Means y devuelve segmentos, centroides y clientes asignados.

La lógica original no fue modificada; únicamente se agregaron comentarios
explicativos.
"""

from __future__ import annotations


from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from .customer_features import build_current_customer_features


# Variables que utilizará K-Means para comparar a los clientes.
# Todas deben ser numéricas y estar disponibles en el DataFrame.
CLUSTER_FEATURE_COLUMNS = [
    "purchase_count",
    "total_spent",
    "avg_purchase",
    "days_since_last_purchase",
    "unique_products",
]

# Nombres legibles que se muestran en la interfaz.
CLUSTER_FEATURE_LABELS = {
    "purchase_count": "Compras",
    "total_spent": "Total comprado",
    "avg_purchase": "Ticket promedio",
    "days_since_last_purchase": "Días desde última compra",
    "unique_products": "Productos distintos",
}

# Se requieren al menos cuatro clientes para intentar formar segmentos.
MIN_CLUSTER_CUSTOMERS = 4

# Evita generar una cantidad excesiva de grupos.
MAX_CLUSTER_COUNT = 6


class ClusterDataError(ValueError):
    """Error generado cuando no existen datos suficientes para K-Means."""


def _safe_cluster_limit(customer_count: int, unique_rows: int) -> int:
    """
    Calcula el máximo número de clústeres permitido.

    El límite no puede superar:
    - MAX_CLUSTER_COUNT.
    - La cantidad de clientes menos uno.
    - La cantidad de filas realmente distintas.
    """
    return max(
        1,
        min(
            MAX_CLUSTER_COUNT,
            customer_count - 1,
            unique_rows,
        ),
    )


def _suggest_k(elbow_data: list[dict[str, float]]) -> int:
    """
    Sugiere K con el punto que tiene mayor distancia perpendicular
    respecto a la línea formada por el primer y último punto del codo.
    """

    if not elbow_data:
        return 2

    if len(elbow_data) == 1:
        return int(elbow_data[0]["k"])

    if len(elbow_data) == 2:
        return int(elbow_data[-1]["k"])

    # Convertir los pares K-WCSS a una matriz numérica.
    points = np.array(
        [
            [float(item["k"]), float(item["wcss"])]
            for item in elbow_data
        ],
        dtype=float,
    )

    # Normalizar los puntos evita que la escala de WCSS domine
    # sobre la escala de K al calcular distancias.
    minimums = points.min(axis=0)
    maximums = points.max(axis=0)
    ranges = maximums - minimums
    ranges[ranges == 0] = 1.0

    normalized_points = (points - minimums) / ranges

    first_point = normalized_points[0]
    last_point = normalized_points[-1]
    line_vector = last_point - first_point
    line_length = float(np.linalg.norm(line_vector))

    if line_length == 0:
        return int(elbow_data[0]["k"])

    # Aquí se guardará la distancia perpendicular de cada punto
    # respecto a la línea entre el primer y el último valor.
    distances: list[float] = []

    for point in normalized_points:
        relative_point = point - first_point

        determinant = abs(
            (line_vector[0] * relative_point[1])
            - (line_vector[1] * relative_point[0])
        )

        distances.append(determinant / line_length)

    elbow_index = int(np.argmax(distances))
    return max(int(elbow_data[elbow_index]["k"]), 2)


def _segment_names(summary: pd.DataFrame) -> dict[int, str]:
    """
    Asigna nombres comerciales según el comportamiento promedio de cada clúster.

    La clasificación compara cada grupo contra las medianas generales para
    determinar si sus clientes son frecuentes, valiosos o inactivos.
    """

    if summary.empty:
        return {}

    comparison_columns = [
        "purchase_count",
        "total_spent",
        "avg_purchase",
        "days_since_last_purchase",
    ]

    # Las medianas funcionan como referencia para decidir si un grupo
    # está por encima o por debajo del comportamiento general.
    medians = summary[comparison_columns].median()
    names: dict[int, str] = {}
    used_names: dict[str, int] = {}

    for _, row in summary.iterrows():
        frequent = row["purchase_count"] >= medians["purchase_count"]
        high_value = row["total_spent"] >= medians["total_spent"]
        high_ticket = row["avg_purchase"] >= medians["avg_purchase"]
        inactive = (
            row["days_since_last_purchase"]
            > medians["days_since_last_purchase"]
        )

        if inactive and not frequent:
            base_name = "Clientes por recuperar"
        elif frequent and high_value:
            base_name = "Frecuentes de alto valor"
        elif high_value or high_ticket:
            base_name = "Clientes de alto valor"
        elif frequent:
            base_name = "Clientes frecuentes"
        else:
            base_name = "Clientes ocasionales"

        used_names[base_name] = used_names.get(base_name, 0) + 1

        final_name = (
            base_name
            if used_names[base_name] == 1
            else f"{base_name} {used_names[base_name]}"
        )

        names[int(row["cluster"])] = final_name

    return names


# Devuelve siempre la misma estructura cuando el análisis no puede ejecutarse.
# Esto evita errores en las rutas o plantillas que consumen el resultado.
def _unavailable_result(
    status: str,
    reason: str,
    customer_count: int,
) -> dict[str, Any]:
    """Devuelve una estructura uniforme cuando K-Means no puede ejecutarse."""

    return {
        "available": False,
        "status": status,
        "reason": reason,
        "message": reason,
        "customer_count": customer_count,
        "selected_k": None,
        "suggested_k": None,
        "max_k": 0,
        "allowed_k_values": [],
        "wcss": None,
        "inertia": None,
        "elbow_data": [],
        "summary": [],
        "cluster_summary": [],
        "centroids": [],
        "customers": [],
        "feature_columns": CLUSTER_FEATURE_COLUMNS,
        "feature_labels": CLUSTER_FEATURE_LABELS,
    }


def analyze_company_clusters(
    database,
    company_id: str,
    requested_k: int | None = None,
) -> dict[str, Any]:
    """
    Ejecuta K-Means para una sola empresa.

    Usa WCSS para construir el método del codo y devuelve también los
    centroides transformados nuevamente a las unidades originales.
    """

    # Generar una fila de características por cada cliente de la empresa.
    dataframe = build_current_customer_features(
        database,
        str(company_id),
    )

    if dataframe.empty:
        return _unavailable_result(
            status="Sin clientes analizables",
            reason="Registra ventas asociadas a clientes para crear segmentos.",
            customer_count=0,
        )

    # Trabajar con una copia evita modificar accidentalmente el DataFrame
    # construido por customer_features.
    dataframe = dataframe.copy()

    # Confirmar que existen todas las columnas requeridas por el modelo.
    missing_columns = [
        column
        for column in CLUSTER_FEATURE_COLUMNS
        if column not in dataframe.columns
    ]

    if missing_columns:
        raise ClusterDataError(
            "Faltan columnas requeridas para K-Means: "
            + ", ".join(missing_columns)
        )

    # Convertir las variables a números, reemplazar infinitos por NaN
    # y completar valores faltantes con cero.
    dataframe[CLUSTER_FEATURE_COLUMNS] = (
        dataframe[CLUSTER_FEATURE_COLUMNS]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
    )

    customer_count = int(len(dataframe))

    if customer_count < MIN_CLUSTER_CUSTOMERS:
        return _unavailable_result(
            status="Datos insuficientes",
            reason=(
                f"K-Means requiere al menos {MIN_CLUSTER_CUSTOMERS} "
                f"clientes con ventas. Actualmente hay {customer_count}."
            ),
            customer_count=customer_count,
        )

    # Matriz final de características que utilizará K-Means.
    X = dataframe[CLUSTER_FEATURE_COLUMNS].astype(float)

    # Estandarizar las variables para que dinero, días y cantidades
    # tengan una escala comparable.
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Contar patrones distintos. Si todos los clientes fueran iguales,
    # no tendría sentido intentar formar varios grupos.
    unique_rows = int(
        np.unique(
            np.round(X_scaled, decimals=10),
            axis=0,
        ).shape[0]
    )

    max_k = _safe_cluster_limit(
        customer_count=customer_count,
        unique_rows=unique_rows,
    )

    if max_k < 2:
        return _unavailable_result(
            status="Sin variedad suficiente",
            reason=(
                "Los clientes tienen características demasiado parecidas "
                "para formar grupos distintos."
            ),
            customer_count=customer_count,
        )

    # Datos utilizados para construir la gráfica del método del codo.
    elbow_data: list[dict[str, float]] = []
    previous_wcss: float | None = None

    # Probar cada valor de K desde 1 hasta el máximo permitido.
    for k in range(1, max_k + 1):
        elbow_model = KMeans(
            n_clusters=k,
            random_state=42,
            n_init=20,
        )

        # Entrenar este modelo temporal únicamente para calcular WCSS.
        elbow_model.fit(X_scaled)
        # inertia_ es el WCSS: suma de distancias cuadradas
        # entre cada cliente y el centroide de su grupo.
        current_wcss = float(elbow_model.inertia_)

        reduction = 0.0
        reduction_percentage = 0.0

        if previous_wcss is not None and previous_wcss > 0:
            reduction = previous_wcss - current_wcss
            reduction_percentage = (reduction / previous_wcss) * 100

        elbow_data.append(
            {
                "k": int(k),
                "wcss": round(current_wcss, 4),
                # Se conserva inertia por compatibilidad con vistas anteriores.
                "inertia": round(current_wcss, 4),
                "reduction": round(reduction, 4),
                "reduction_percentage": round(reduction_percentage, 2),
            }
        )

        previous_wcss = current_wcss

    # Seleccionar automáticamente el punto del codo y limitarlo
    # al rango válido de clústeres.
    suggested_k = min(
        max(_suggest_k(elbow_data), 2),
        max_k,
    )

    selected_k = suggested_k

    if requested_k is not None:
        selected_k = min(
            max(int(requested_k), 2),
            max_k,
        )

    # Crear el modelo final con el K seleccionado.
    model = KMeans(
        n_clusters=selected_k,
        random_state=42,
        n_init=20,
    )

    # Entrenar el modelo y guardar el clúster asignado a cada cliente.
    dataframe["cluster"] = model.fit_predict(X_scaled).astype(int)

    # Distancia de cada cliente a su centroide asignado.
    # Obtener para cada cliente el centroide del grupo al que pertenece.
    assigned_centroids = model.cluster_centers_[dataframe["cluster"].to_numpy()]
    # Una distancia menor indica que el cliente se parece más
    # al comportamiento promedio de su segmento.
    dataframe["distance_to_centroid"] = np.linalg.norm(
        X_scaled - assigned_centroids,
        axis=1,
    )

    # Calcular promedios y cantidad de clientes para cada clúster.
    summary = (
        dataframe.groupby("cluster", as_index=False)
        .agg(
            customers=("client_id", "count"),
            purchase_count=("purchase_count", "mean"),
            total_spent=("total_spent", "mean"),
            avg_purchase=("avg_purchase", "mean"),
            days_since_last_purchase=(
                "days_since_last_purchase",
                "mean",
            ),
            unique_products=("unique_products", "mean"),
            average_distance=("distance_to_centroid", "mean"),
        )
        .round(2)
    )

    # Traducir los números de clúster a nombres comerciales.
    segment_names = _segment_names(summary)

    summary["segment_name"] = summary["cluster"].map(segment_names)
    dataframe["segment_name"] = dataframe["cluster"].map(segment_names)

    # Los centroides del modelo están escalados. Se regresan a las unidades
    # originales para poder mostrarlos en la interfaz.
    # Los centroides están normalizados. Regresarlos a unidades originales
    # permite mostrar compras, dinero, días y productos comprensibles.
    original_centroids = scaler.inverse_transform(model.cluster_centers_)

    centroids: list[dict[str, Any]] = []

    for cluster_index, centroid_values in enumerate(original_centroids):
        centroid = {
            "cluster": int(cluster_index),
            "segment_name": segment_names.get(
                int(cluster_index),
                f"Clúster {cluster_index}",
            ),
        }

        for feature_index, feature_name in enumerate(CLUSTER_FEATURE_COLUMNS):
            centroid[feature_name] = round(
                float(centroid_values[feature_index]),
                2,
            )

        centroids.append(centroid)

    customers: list[dict[str, Any]] = []

    # Ordenar primero por clúster y después por cercanía al centroide.
    sorted_customers = dataframe.sort_values(
        ["cluster", "distance_to_centroid", "total_spent"],
        ascending=[True, True, False],
    )

    for row in sorted_customers.to_dict("records"):
        customers.append(
            {
                "client_id": str(row["client_id"]),
                "client_name": row.get("client_name") or "Cliente sin nombre",
                "cluster": int(row["cluster"]),
                "segment_name": row["segment_name"],
                "purchase_count": int(round(float(row["purchase_count"]))),
                "total_spent": round(float(row["total_spent"]), 2),
                "avg_purchase": round(float(row["avg_purchase"]), 2),
                "average_ticket": round(float(row["avg_purchase"]), 2),
                "days_since_last_purchase": int(
                    round(float(row["days_since_last_purchase"]))
                ),
                "unique_products": int(
                    round(float(row["unique_products"]))
                ),
                "distance_to_centroid": round(
                    float(row["distance_to_centroid"]),
                    4,
                ),
            }
        )

    summaries: list[dict[str, Any]] = []

    for row in summary.sort_values("cluster").to_dict("records"):
        summaries.append(
            {
                "cluster": int(row["cluster"]),
                "segment_name": row["segment_name"],
                "customers": int(row["customers"]),
                "customer_count": int(row["customers"]),
                "purchase_count": float(row["purchase_count"]),
                "total_spent": float(row["total_spent"]),
                "avg_purchase": float(row["avg_purchase"]),
                "average_ticket": float(row["avg_purchase"]),
                "days_since_last_purchase": float(
                    row["days_since_last_purchase"]
                ),
                "unique_products": float(row["unique_products"]),
                "average_distance": float(row["average_distance"]),
            }
        )

    # WCSS correspondiente al modelo final seleccionado.
    selected_wcss = round(float(model.inertia_), 4)

    # Estructura final consumida por la ruta Flask y la plantilla HTML.
    return {
        "available": True,
        "status": "Analizado",
        "reason": (
            "Los clientes fueron agrupados por similitud "
            "en su comportamiento de compra."
        ),
        "message": (
            "Los clientes fueron agrupados por similitud "
            "en su comportamiento de compra."
        ),
        "customer_count": customer_count,
        "selected_k": selected_k,
        "suggested_k": suggested_k,
        "max_k": max_k,
        "allowed_k_values": list(range(2, max_k + 1)),
        "wcss": selected_wcss,
        "inertia": selected_wcss,
        "elbow_data": elbow_data,
        "summary": summaries,
        "cluster_summary": summaries,
        "centroids": centroids,
        "customers": customers,
        "feature_columns": CLUSTER_FEATURE_COLUMNS,
        "feature_labels": CLUSTER_FEATURE_LABELS,
    }