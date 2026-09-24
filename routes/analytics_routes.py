from __future__ import annotations
from helpers.machine_learning.trial_error_search import (
    run_trial_error_search,
)
from bson import ObjectId
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

import extensions as ext
from helpers.machine_learning.customer_features import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    build_training_dataset,
    get_company_clients_status,
    get_company_data_summary,
)
from helpers.machine_learning.kmeans_analysis import analyze_company_clusters
from helpers.machine_learning.model_manager import load_model, model_exists
from helpers.machine_learning.predict import predict_company_customers
from helpers.analytics.matplotlib_reports import generate_developer_matplotlib_analysis
from helpers.machine_learning.train_model import (
    MIN_CUSTOMERS,
    MIN_ROWS_PER_CLASS,
    MIN_TRAINING_ROWS,
    TrainingDataError,
    train_company_model,
)

analytics_bp = Blueprint("analytics", __name__, url_prefix="/analytics")


def db():
    return ext.db


def developer_required() -> bool:
    return bool(session.get("user_id") and session.get("role") == "developer")


def logged_company_required() -> bool:
    return bool(session.get("user_id") and session.get("company_id"))


def find_company(company_id: str):
    try:
        object_id = ObjectId(company_id)
    except Exception:
        return None

    return db()["companies"].find_one({"_id": object_id})


def read_model_metadata(company_id: str):
    if not model_exists(company_id):
        return None

    try:
        package = load_model(company_id)
    except Exception:
        return None

    metadata = {
        key: value
        for key, value in package.items()
        if key != "model"
    }

    # Ignora modelos anteriores que usaban otro objetivo.
    if metadata.get("target_column") != TARGET_COLUMN:
        return None

    return metadata


def company_is_ready(summary: dict) -> bool:
    return bool(
        summary.get("training_rows", 0) >= MIN_TRAINING_ROWS
        and summary.get("positive_rows", 0) >= MIN_ROWS_PER_CLASS
        and summary.get("negative_rows", 0) >= MIN_ROWS_PER_CLASS
        and summary.get("customers_with_sales", 0) >= MIN_CUSTOMERS
    )


def training_requirements_message(summary: dict) -> str:
    problems: list[str] = []

    rows = int(summary.get("training_rows", 0) or 0)
    positives = int(summary.get("positive_rows", 0) or 0)
    negatives = int(summary.get("negative_rows", 0) or 0)
    customers = int(summary.get("customers_with_sales", 0) or 0)

    if rows < MIN_TRAINING_ROWS:
        missing = MIN_TRAINING_ROWS - rows
        problems.append(
            f"faltan {missing} ejemplos "
            f"(hay {rows} de {MIN_TRAINING_ROWS})"
        )

    if positives < MIN_ROWS_PER_CLASS:
        problems.append("falta al menos un caso de recompra")

    if negatives < MIN_ROWS_PER_CLASS:
        problems.append("falta al menos un caso de no recompra")

    if customers < MIN_CUSTOMERS:
        missing = MIN_CUSTOMERS - customers
        problems.append(f"faltan {missing} clientes con ventas")

    if not problems:
        return "Los datos ya permiten entrenar el modelo."

    return "No se puede entrenar todavía: " + "; ".join(problems) + "."


def company_model_status(summary: dict, model: dict | None) -> dict:
    if summary.get("total_sales", 0) == 0:
        return {
            "key": "no_sales",
            "label": "Sin ventas",
            "badge": "secondary",
            "reason": "La empresa todavía no tiene ventas registradas.",
        }

    if summary.get("identified_sales", 0) == 0:
        return {
            "key": "no_identified",
            "label": "Sin clientes identificables",
            "badge": "secondary",
            "reason": (
                "Las ventas rápidas no permiten reconocer si el mismo "
                "cliente volvió a comprar."
            ),
        }

    if summary.get("training_rows", 0) == 0:
        return {
            "key": "no_history",
            "label": "Sin ejemplos",
            "badge": "secondary",
            "reason": (
                "No existen ventas con cliente y fecha válida para "
                "construir ejemplos."
            ),
        }

    if (
        summary.get("positive_rows", 0) == 0
        or summary.get("negative_rows", 0) == 0
    ):
        return {
            "key": "one_class",
            "label": "Falta variedad",
            "badge": "warning",
            "reason": (
                "Debe existir al menos un cliente que haya recomprado "
                "y un caso sin recompra posterior."
            ),
        }

    if not company_is_ready(summary):
        return {
            "key": "insufficient",
            "label": "Datos insuficientes",
            "badge": "warning",
            "reason": (
                "Aún no se cumplen los mínimos básicos para ejecutar "
                "el modelo."
            ),
        }

    if model:
        trained_rows = int(model.get("training_rows", 0) or 0)

        if summary.get("training_rows", 0) > trained_rows:
            return {
                "key": "retrain",
                "label": "Actualizar modelo",
                "badge": "warning",
                "reason": "Hay nuevas ventas desde el último entrenamiento.",
            }

        return {
            "key": "trained",
            "label": "Entrenado",
            "badge": "success",
            "reason": "El modelo está disponible para generar predicciones.",
        }

    return {
        "key": "ready",
        "label": "Listo para entrenar",
        "badge": "primary",
        "reason": "Los datos actuales ya permiten entrenar el Random Forest.",
    }


def training_preview(company_id: str, limit: int = 20) -> list[dict]:
    dataframe = build_training_dataset(db(), company_id)

    if dataframe.empty:
        return []

    preview = (
        dataframe
        .sort_values("reference_date", ascending=False)
        .head(limit)
        .copy()
    )

    return preview.to_dict("records")


def prepare_clients_with_predictions(company_id: str, metadata: dict | None):
    clients_status = get_company_clients_status(db(), company_id)
    predictions: list[dict] = []

    if metadata:
        try:
            predictions, _ = predict_company_customers(db(), company_id)
        except Exception as exc:
            flash(
                f"No fue posible calcular las predicciones: {exc}",
                "warning",
            )

    predictions_by_client = {
        str(item["client_id"]): item
        for item in predictions
    }

    for client in clients_status:
        client_id = str(client["client_id"])
        prediction = predictions_by_client.get(client_id)

        if prediction:
            client["probability"] = prediction.get("probability")
            client["level"] = prediction.get("level")
            client["prediction_status"] = "available"
        elif not client.get("has_sales"):
            client["probability"] = None
            client["level"] = "Sin ventas"
            client["prediction_status"] = "no_sales"
        elif not metadata:
            client["probability"] = None
            client["level"] = "Modelo no disponible"
            client["prediction_status"] = "no_model"
        else:
            client["probability"] = None
            client["level"] = "Sin datos suficientes"
            client["prediction_status"] = "no_features"

    return clients_status


# ---------------------------------------------------------------------------
# Developer: listado y detalle de Random Forest por empresa
# ---------------------------------------------------------------------------

@analytics_bp.route("/developer/models")
def developer_models():
    if not developer_required():
        return redirect(url_for("login"))

    companies = list(db()["companies"].find().sort("name", 1))
    rows: list[dict] = []

    for company in companies:
        company_id = str(company["_id"])
        summary = get_company_data_summary(db(), company_id)
        metadata = read_model_metadata(company_id)

        rows.append({
            "id": company_id,
            "name": company.get("name", "Sin nombre"),
            "plan": company.get("plan_name") or company.get("plan") or "basic",
            "active": company.get("active", True),
            "summary": summary,
            "model": metadata,
            "ready": company_is_ready(summary),
            "status": company_model_status(summary, metadata),
        })

    totals = {
        "companies": len(rows),
        "trained": sum(
            1 for row in rows
            if row["status"]["key"] == "trained"
        ),
        "ready": sum(
            1 for row in rows
            if row["status"]["key"] in {"ready", "retrain"}
        ),
        "insufficient": sum(
            1 for row in rows
            if row["status"]["key"] not in {"trained", "ready", "retrain"}
        ),
    }

    return render_template(
        "analytics/developer_models.html",
        companies=rows,
        totals=totals,
    )


@analytics_bp.route("/developer/models/<company_id>")
def developer_company_model(company_id: str):
    if not developer_required():
        return redirect(url_for("login"))

    company = find_company(company_id)

    if not company:
        flash("Empresa no encontrada.", "danger")
        return redirect(url_for("analytics.developer_models"))

    summary = get_company_data_summary(db(), company_id)
    metadata = read_model_metadata(company_id)
    clients_status = prepare_clients_with_predictions(company_id, metadata)

    return render_template(
        "analytics/developer_company_model.html",
        company={
            "id": company_id,
            "name": company.get("name", "Sin nombre"),
            "plan": company.get("plan_name") or company.get("plan") or "basic",
        },
        summary=summary,
        model=metadata,
        status=company_model_status(summary, metadata),
        clients_status=clients_status,
        training_preview=training_preview(company_id),
        feature_columns=FEATURE_COLUMNS,
        target_column=TARGET_COLUMN,
        ready=company_is_ready(summary),
        min_training_rows=MIN_TRAINING_ROWS,
        min_rows_per_class=MIN_ROWS_PER_CLASS,
        min_customers=MIN_CUSTOMERS,
        company_view=False,
        cluster_analysis={},
    )


@analytics_bp.route(
    "/developer/models/<company_id>/train",
    methods=["POST"],
)
def train_developer_company_model(company_id: str):
    if not developer_required():
        return redirect(url_for("login"))

    company = find_company(company_id)

    if not company:
        flash("Empresa no encontrada.", "danger")
        return redirect(url_for("analytics.developer_models"))

    summary = get_company_data_summary(db(), company_id)

    if not company_is_ready(summary):
        flash(training_requirements_message(summary), "warning")
        return redirect(
            url_for(
                "analytics.developer_company_model",
                company_id=company_id,
            )
        )

    try:
        result = train_company_model(
            db(),
            company_id,
            company.get("name", ""),
        )
    except TrainingDataError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        flash(f"Error durante el entrenamiento: {exc}", "danger")
    else:
        accuracy = result["metrics"]["accuracy"] * 100
        flash(
            "Modelo entrenado correctamente. "
            f"Exactitud de prueba: {accuracy:.2f}%.",
            "success",
        )

    return redirect(
        url_for(
            "analytics.developer_company_model",
            company_id=company_id,
        )
    )


@analytics_bp.route("/developer/models/<company_id>/kmeans")
def developer_company_kmeans(company_id: str):
    if not developer_required():
        return redirect(url_for("login"))

    company = find_company(company_id)

    if not company:
        flash("Empresa no encontrada.", "danger")
        return redirect(url_for("analytics.developer_models"))

    requested_k = request.args.get("cluster_k", type=int)

    cluster_analysis = analyze_company_clusters(
        db(),
        company_id,
        requested_k=requested_k,
    )

    return render_template(
        "analytics/company_kmeans.html",
        company={
            "id": company_id,
            "name": company.get("name", "Sin nombre"),
            "plan": company.get("plan_name") or company.get("plan") or "basic",
        },
        cluster_analysis=cluster_analysis,
        developer_view=True,
    )


# ---------------------------------------------------------------------------
# Empresa autenticada: Random Forest propio
# ---------------------------------------------------------------------------

@analytics_bp.route("/company/random-forest")
def company_random_forest():
    if not logged_company_required():
        flash("Debes iniciar sesión con una empresa.", "warning")
        return redirect(url_for("login"))

    company_id = str(session["company_id"])
    company = find_company(company_id)

    if not company:
        flash("No se encontró la empresa.", "danger")
        return redirect(url_for("login"))

    summary = get_company_data_summary(db(), company_id)
    metadata = read_model_metadata(company_id)
    clients_status = prepare_clients_with_predictions(company_id, metadata)

    return render_template(
        "analytics/developer_company_model.html",
        company={
            "id": company_id,
            "name": company.get("name", "Sin nombre"),
            "plan": company.get("plan_name") or company.get("plan") or "basic",
        },
        summary=summary,
        model=metadata,
        status=company_model_status(summary, metadata),
        clients_status=clients_status,
        training_preview=training_preview(company_id),
        feature_columns=FEATURE_COLUMNS,
        target_column=TARGET_COLUMN,
        ready=company_is_ready(summary),
        min_training_rows=MIN_TRAINING_ROWS,
        min_rows_per_class=MIN_ROWS_PER_CLASS,
        min_customers=MIN_CUSTOMERS,
        company_view=True,
        cluster_analysis={},
    )


@analytics_bp.route(
    "/company/random-forest/train",
    methods=["POST"],
)
def train_company_random_forest():
    if not logged_company_required():
        flash("Debes iniciar sesión con una empresa.", "warning")
        return redirect(url_for("login"))

    company_id = str(session["company_id"])
    company = find_company(company_id)

    if not company:
        flash("No se encontró la empresa.", "danger")
        return redirect(url_for("login"))

    summary = get_company_data_summary(db(), company_id)

    if not company_is_ready(summary):
        flash(training_requirements_message(summary), "warning")
        return redirect(url_for("analytics.company_random_forest"))

    try:
        result = train_company_model(
            db(),
            company_id,
            company.get("name", ""),
        )
    except TrainingDataError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        flash(f"No fue posible entrenar el modelo: {exc}", "danger")
    else:
        accuracy = result["metrics"]["accuracy"] * 100
        flash(
            "Modelo Random Forest entrenado correctamente. "
            f"Exactitud de prueba: {accuracy:.2f}%.",
            "success",
        )

    return redirect(url_for("analytics.company_random_forest"))


# ---------------------------------------------------------------------------
# Empresa autenticada: K-Means y método del codo propios
# ---------------------------------------------------------------------------

@analytics_bp.route("/company/kmeans")
def company_kmeans():
    if not logged_company_required():
        flash("Debes iniciar sesión con una empresa.", "warning")
        return redirect(url_for("login"))

    company_id = str(session["company_id"])
    company = find_company(company_id)

    if not company:
        flash("No se encontró la empresa.", "danger")
        return redirect(url_for("login"))

    requested_k = request.args.get("cluster_k", type=int)

    try:
        cluster_analysis = analyze_company_clusters(
            db(),
            company_id,
            requested_k=requested_k,
        )
    except Exception as exc:
        flash(f"No fue posible ejecutar K-Means: {exc}", "danger")
        cluster_analysis = {
            "available": False,
            "message": "Ocurrió un error al analizar los clientes.",
        }

    return render_template(
        "analytics/company_kmeans.html",
        company={
            "id": company_id,
            "name": company.get("name", "Sin nombre"),
        },
        cluster_analysis=cluster_analysis,
    )
@analytics_bp.route(
    "/developer/models/<company_id>/trial-error"
)
def developer_trial_error(
    company_id: str,
):
    if not developer_required():
        return redirect(
            url_for("login")
        )

    company = find_company(
        company_id
    )

    if not company:
        flash(
            "Empresa no encontrada.",
            "danger",
        )

        return redirect(
            url_for(
                "analytics.developer_models"
            )
        )

    summary = get_company_data_summary(
        db(),
        company_id,
    )

    return render_template(
        "analytics/developer_trial_error.html",

        company={
            "id": company_id,
            "name": company.get(
                "name",
                "Sin nombre",
            ),
        },

        summary=summary,

        results=None,
    )


@analytics_bp.route(
    "/developer/models/<company_id>/trial-error/run",
    methods=["POST"],
)
def run_developer_trial_error(
    company_id: str,
):
    if not developer_required():
        return redirect(
            url_for("login")
        )

    company = find_company(
        company_id
    )

    if not company:
        flash(
            "Empresa no encontrada.",
            "danger",
        )

        return redirect(
            url_for(
                "analytics.developer_models"
            )
        )

    summary = get_company_data_summary(
        db(),
        company_id,
    )

    try:
        results = run_trial_error_search(
            db(),
            company_id,
            company.get(
                "name",
                "",
            ),
        )

    except TrainingDataError as exc:
        flash(
            str(exc),
            "warning",
        )

        results = None

    except Exception as exc:
        flash(
            f"Error durante las pruebas: {exc}",
            "danger",
        )

        results = None

    else:
        flash(
            (
                "Prueba y error finalizada. "
                f"Se evaluaron {results['total_trials']} "
                "configuraciones y se guardó la mejor."
            ),
            "success",
        )

    return render_template(
        "analytics/developer_trial_error.html",

        company={
            "id": company_id,
            "name": company.get(
                "name",
                "Sin nombre",
            ),
        },

        summary=summary,

        results=results,
    )

# ---------------------------------------------------------------------------
# Developer: visualización de datos con Python + Matplotlib
# ---------------------------------------------------------------------------

@analytics_bp.route("/developer/matplotlib")
def developer_matplotlib():
    if not developer_required():
        return redirect(url_for("login"))

    company_id = (request.args.get("company_id") or "").strip()
    months = request.args.get("months", default=6, type=int)

    if months not in {0, 3, 6, 12}:
        months = 6

    companies = list(
        db()["companies"].find(
            {},
            {
                "_id": 1,
                "name": 1,
                "plan": 1,
                "plan_name": 1,
                "active": 1,
            },
        ).sort("name", 1)
    )

    companies_for_view = [
        {
            "id": str(company["_id"]),
            "name": company.get("name", "Sin nombre"),
            "plan": company.get("plan_name") or company.get("plan") or "Sin plan",
            "active": company.get("active", True),
        }
        for company in companies
    ]

    selected_company = None

    if company_id:
        selected_company = next(
            (
                company
                for company in companies_for_view
                if company["id"] == company_id
            ),
            None,
        )

        if not selected_company:
            flash("La empresa seleccionada no existe.", "warning")
            company_id = ""

    try:
        analysis = generate_developer_matplotlib_analysis(
            db(),
            company_id=company_id or None,
            months=months,
        )
    except Exception as exc:
        flash(
            f"No fue posible generar el análisis con Matplotlib: {exc}",
            "danger",
        )
        analysis = {
            "available": False,
            "message": "No fue posible generar el análisis.",
            "monthly_chart": None,
            "companies_chart": None,
            "products_chart": None,
            "summary": {
                "sales_count": 0,
                "sales_total": 0,
                "average_ticket": 0,
            },
            "interpretation": [],
            "period_label": "Sin datos",
        }

    return render_template(
        "analytics/developer_matplotlib.html",
        companies=companies_for_view,
        selected_company_id=company_id,
        selected_company=selected_company,
        selected_months=months,
        analysis=analysis,
    )

