from __future__ import annotations

import base64
import io
import textwrap
from datetime import datetime

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


MONTH_NAMES = {
    1: "Ene",
    2: "Feb",
    3: "Mar",
    4: "Abr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dic",
}


# =========================
# CONFIGURACIÓN GLOBAL
# =========================
plt.rcParams.update({
    "figure.facecolor": "#ffffff",
    "savefig.facecolor": "#ffffff",
    "axes.facecolor": "#ffffff",
    "axes.edgecolor": "#e2e8f0",
    "axes.labelcolor": "#334155",
    "axes.titlecolor": "#0f172a",
    "xtick.color": "#64748b",
    "ytick.color": "#64748b",
    "text.color": "#0f172a",
    "axes.titleweight": "bold",
    "axes.titlesize": 16,
    "axes.labelsize": 10,
    "font.size": 10,
    "font.family": "DejaVu Sans",
    "grid.color": "#e2e8f0",
    "grid.linestyle": "--",
    "grid.linewidth": 0.8,
})


def _currency(value) -> str:
    return f"${value:,.0f}"


def _currency_formatter():
    return FuncFormatter(lambda value, position: _currency(value))


def _int_formatter():
    return FuncFormatter(lambda value, position: f"{int(value):,}")


def _wrap_label(text: str, width: int = 18) -> str:
    if not text:
        return "Sin nombre"
    return "\n".join(textwrap.wrap(str(text), width=width))


def _truncate_label(text: str, limit: int = 28) -> str:
    if not text:
        return "Sin nombre"
    text = str(text)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _start_date_for_months(months: int) -> datetime | None:
    """
    months=0 => todo el historial
    """
    if months == 0:
        return None

    now = datetime.utcnow()
    year = now.year
    month = now.month - (months - 1)

    while month <= 0:
        month += 12
        year -= 1

    return datetime(year, month, 1)


def _period_info(months: int) -> dict:
    """
    Información legible del plazo seleccionado.
    El filtro comienza el primer día del mes inicial y termina en la fecha actual.
    """
    now = datetime.utcnow()
    start_date = _start_date_for_months(months)

    if months == 0:
        return {
            "months": 0,
            "start_date": None,
            "end_date": now,
            "short_label": "Todo el historial",
            "range_label": f"Hasta {now.strftime('%d/%m/%Y')}",
            "full_label": f"Plazo seleccionado: todo el historial · Hasta {now.strftime('%d/%m/%Y')}",
        }

    return {
        "months": months,
        "start_date": start_date,
        "end_date": now,
        "short_label": f"Últimos {months} meses",
        "range_label": (
            f"{start_date.strftime('%d/%m/%Y')} al "
            f"{now.strftime('%d/%m/%Y')}"
        ),
        "full_label": (
            f"Plazo seleccionado: últimos {months} meses · "
            f"Periodo: {start_date.strftime('%d/%m/%Y')} al "
            f"{now.strftime('%d/%m/%Y')}"
        ),
    }


def _sales_match(company_id: str | None, months: int) -> dict:
    match: dict = {
        "payment_status": "paid",
    }

    if company_id:
        match["company_id"] = str(company_id)

    start_date = _start_date_for_months(months)

    if start_date:
        match["created_at"] = {"$gte": start_date}

    return match


def _figure_to_base64(fig) -> str:
    buffer = io.BytesIO()

    fig.savefig(
        buffer,
        format="png",
        dpi=160,
        bbox_inches="tight",
        facecolor="white",
    )

    plt.close(fig)
    buffer.seek(0)

    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _empty_chart(title: str, message: str = "Sin datos para mostrar") -> str:
    fig, ax = plt.subplots(figsize=(11.5, 5.4))
    ax.axis("off")

    fig.text(
        0.06,
        0.90,
        title,
        fontsize=17,
        fontweight="bold",
        color="#0f172a",
    )

    fig.text(
        0.06,
        0.84,
        "No se encontraron registros para los filtros seleccionados.",
        fontsize=10,
        color="#64748b",
    )

    ax.text(
        0.5,
        0.47,
        message,
        ha="center",
        va="center",
        fontsize=13,
        fontweight="bold",
        transform=ax.transAxes,
        color="#94a3b8",
        bbox={
            "boxstyle": "round,pad=1.2",
            "facecolor": "#f8fafc",
            "edgecolor": "#e2e8f0",
        },
    )

    return _figure_to_base64(fig)

# =========================
# CONSULTAS
# =========================
def _monthly_sales_data(database, match: dict) -> list[dict]:
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$created_at"},
                    "month": {"$month": "$created_at"},
                },
                "sales_total": {"$sum": "$total"},
                "sales_count": {"$sum": 1},
            }
        },
        {
            "$sort": {
                "_id.year": 1,
                "_id.month": 1,
            }
        },
    ]

    return list(database["sales"].aggregate(pipeline))


def _top_companies_data(database, match: dict) -> list[dict]:
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": "$company_id",
                "company_name": {"$first": "$company_name"},
                "sales_total": {"$sum": "$total"},
                "sales_count": {"$sum": 1},
            }
        },
        {"$sort": {"sales_total": -1}},
        {"$limit": 8},
    ]

    rows = list(database["sales"].aggregate(pipeline))

    company_name_map = {
        str(company["_id"]): company.get("name", "Sin nombre")
        for company in database["companies"].find({}, {"name": 1})
    }

    for row in rows:
        company_id = str(row.get("_id") or "")
        row["company_name"] = (
            row.get("company_name")
            or company_name_map.get(company_id)
            or "Sin nombre"
        )

    return rows


def _top_products_data(database, match: dict) -> list[dict]:
    pipeline = [
        {
            "$match": match
        },

        {
            "$unwind": "$items"
        },

        # Convertimos todos los campos numéricos
        {
            "$addFields": {
                "_item_quantity": {
                    "$convert": {
                        "input": "$items.quantity",
                        "to": "double",
                        "onError": 0,
                        "onNull": 0
                    }
                },

                "_item_unit_price": {
                    "$convert": {
                        "input": "$items.unit_price",
                        "to": "double",
                        "onError": 0,
                        "onNull": 0
                    }
                },

                "_item_subtotal": {
                    "$convert": {
                        "input": "$items.subtotal",
                        "to": "double",
                        "onError": 0,
                        "onNull": 0
                    }
                }
            }
        },

        # Determinamos la cantidad real.
        #
        # 1. Si quantity > 0, usamos quantity.
        # 2. Si quantity viene vacío/0, calculamos subtotal / unit_price.
        # 3. Si tampoco se puede calcular, asumimos 1 unidad.
        {
            "$addFields": {
                "_real_quantity": {
                    "$cond": [
                        {
                            "$gt": [
                                "$_item_quantity",
                                0
                            ]
                        },
                        "$_item_quantity",

                        {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$gt": [
                                                "$_item_unit_price",
                                                0
                                            ]
                                        },
                                        {
                                            "$gt": [
                                                "$_item_subtotal",
                                                0
                                            ]
                                        }
                                    ]
                                },

                                {
                                    "$divide": [
                                        "$_item_subtotal",
                                        "$_item_unit_price"
                                    ]
                                },

                                1
                            ]
                        }
                    ]
                }
            }
        },

        {
            "$group": {
                "_id": {
                    "sku": "$items.sku",
                    "name": "$items.product_name"
                },

                "units": {
                    "$sum": "$_real_quantity"
                },

                "sales_total": {
                    "$sum": "$_item_subtotal"
                }
            }
        },

        {
            "$sort": {
                "units": -1,
                "sales_total": -1
            }
        },

        {
            "$limit": 8
        }
    ]

    rows = list(
        database["sales"].aggregate(pipeline)
    )

    return rows


def _summary_data(database, match: dict) -> dict:
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": None,
                "sales_total": {"$sum": "$total"},
                "sales_count": {"$sum": 1},
            }
        },
    ]

    rows = list(database["sales"].aggregate(pipeline))

    if not rows:
        return {
            "sales_total": 0.0,
            "sales_count": 0,
            "average_ticket": 0.0,
        }

    sales_total = float(rows[0].get("sales_total", 0) or 0)
    sales_count = int(rows[0].get("sales_count", 0) or 0)

    return {
        "sales_total": sales_total,
        "sales_count": sales_count,
        "average_ticket": sales_total / sales_count if sales_count else 0.0,
    }


# =========================
# GRÁFICAS MEJORADAS
# =========================
def _monthly_chart(rows: list[dict], period: dict) -> str:
    if not rows:
        return _empty_chart("Tendencia mensual de ventas")

    labels = [
        f"{MONTH_NAMES.get(row['_id']['month'], row['_id']['month'])} {row['_id']['year']}"
        for row in rows
    ]
    values = [float(row.get("sales_total", 0) or 0) for row in rows]
    counts = [int(row.get("sales_count", 0) or 0) for row in rows]

    fig, ax = plt.subplots(figsize=(12.8, 6.7))

    line_color = "#2563eb"
    fill_color = "#dbeafe"

    # Cabecera editorial
    fig.text(
        0.075, 0.945,
        "Tendencia mensual de ventas",
        fontsize=18,
        fontweight="bold",
        color="#0f172a",
    )
    fig.text(
        0.075, 0.905,
        period["full_label"],
        fontsize=10,
        color="#64748b",
    )

    # Serie
    ax.plot(
        labels,
        values,
        marker="o",
        linewidth=3.0,
        markersize=8,
        color=line_color,
        markerfacecolor="#ffffff",
        markeredgecolor=line_color,
        markeredgewidth=2.2,
        zorder=3,
    )
    ax.fill_between(
        range(len(labels)),
        values,
        color=fill_color,
        alpha=0.65,
        zorder=1,
    )

    # Valor encima de cada punto
    max_value = max(values) if values else 0
    offset = max(max_value * 0.045, 1)

    for i, (value, count) in enumerate(zip(values, counts)):
        ax.annotate(
            f"${value:,.2f}\n{count} venta{'s' if count != 1 else ''}",
            xy=(i, value),
            xytext=(0, 14),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8.6,
            fontweight="bold",
            color="#1e3a8a",
            bbox={
                "boxstyle": "round,pad=0.35",
                "facecolor": "#eff6ff",
                "edgecolor": "#bfdbfe",
                "alpha": 0.96,
            },
        )

    ax.set_xlabel(
        "Eje X — Mes y año de la venta",
        fontsize=10.5,
        fontweight="bold",
        color="#475569",
        labelpad=14,
    )
    ax.set_ylabel(
        "Eje Y — Importe de ventas pagadas (MXN)",
        fontsize=10.5,
        fontweight="bold",
        color="#475569",
        labelpad=14,
    )

    ax.yaxis.set_major_formatter(_currency_formatter())
    ax.grid(axis="y", alpha=0.9)
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)

    ax.tick_params(axis="x", rotation=0, labelsize=9.5, pad=8)
    ax.tick_params(axis="y", labelsize=9)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0")
    ax.spines["bottom"].set_color("#e2e8f0")

    if max_value > 0:
        ax.set_ylim(0, max_value * 1.28)

    fig.subplots_adjust(
        left=0.105,
        right=0.97,
        top=0.82,
        bottom=0.16,
    )

    return _figure_to_base64(fig)

def _companies_chart(rows: list[dict], period: dict) -> str:
    title = "Total de ventas por empresa"

    if not rows:
        return _empty_chart(title)

    rows = rows[:6]

    labels = [
        _truncate_label(row.get("company_name", "Sin nombre"), 28)
        for row in rows
    ]
    values = [float(row.get("sales_total", 0) or 0) for row in rows]
    counts = [int(row.get("sales_count", 0) or 0) for row in rows]

    labels = labels[::-1]
    values = values[::-1]
    counts = counts[::-1]

    fig, ax = plt.subplots(figsize=(12.8, 6.9))

    fig.text(
        0.075, 0.945,
        title,
        fontsize=18,
        fontweight="bold",
        color="#0f172a",
    )
    fig.text(
        0.075, 0.905,
        period["full_label"],
        fontsize=10,
        color="#64748b",
    )

    bars = ax.barh(
        labels,
        values,
        height=0.56,
        color="#2563eb",
        alpha=0.92,
        edgecolor="#1d4ed8",
        linewidth=0.7,
        zorder=3,
    )

    max_value = max(values) if values else 0
    right_space = max(max_value * 0.46, 1)
    ax.set_xlim(0, max_value + right_space if max_value > 0 else 1)

    for index, (bar, value, count) in enumerate(zip(bars, values, counts)):
        y = bar.get_y() + bar.get_height() / 2
        ranking = len(values) - index

        # Ranking dentro de la barra
        if max_value and value > max_value * 0.09:
            ax.text(
                max_value * 0.014,
                y,
                f"#{ranking}",
                va="center",
                ha="left",
                fontsize=9,
                fontweight="bold",
                color="#ffffff",
                zorder=4,
            )

        # KPI lateral
        label_x = value + (max_value * 0.025 if max_value else 0.1)
        ax.text(
            label_x,
            y + 0.085,
            f"${value:,.2f}",
            va="center",
            ha="left",
            fontsize=10.2,
            fontweight="bold",
            color="#0f172a",
        )
        ax.text(
            label_x,
            y - 0.115,
            f"{count} venta{'s' if count != 1 else ''}",
            va="center",
            ha="left",
            fontsize=8.6,
            color="#64748b",
        )

    ax.set_xlabel(
        "Eje X — Total acumulado de ventas pagadas (MXN)",
        fontsize=10.2,
        fontweight="bold",
        color="#475569",
        labelpad=14,
    )
    ax.set_ylabel(
        "Eje Y — Empresa",
        fontsize=10.2,
        fontweight="bold",
        color="#475569",
        labelpad=14,
    )

    ax.xaxis.set_major_formatter(_currency_formatter())
    ax.grid(axis="x", alpha=0.9)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)

    ax.tick_params(axis="y", length=0, labelsize=10, pad=10)
    ax.tick_params(axis="x", labelsize=9)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color("#e2e8f0")

    fig.subplots_adjust(
        left=0.25,
        right=0.95,
        top=0.82,
        bottom=0.17,
    )

    return _figure_to_base64(fig)

def _products_chart(rows: list[dict], period: dict) -> str:
    title = "Productos más vendidos"

    if not rows:
        return _empty_chart(title)

    rows = rows[:6]

    labels = []
    units = []
    totals = []

    for row in rows:
        product_name = (
            row.get("_id", {}).get("name")
            or row.get("_id", {}).get("sku")
            or "Sin nombre"
        )
        labels.append(_truncate_label(product_name, 34))
        units.append(float(row.get("units", 0) or 0))
        totals.append(float(row.get("sales_total", 0) or 0))

    labels = labels[::-1]
    units = units[::-1]
    totals = totals[::-1]

    fig, ax = plt.subplots(figsize=(12.8, 6.9))

    fig.text(
        0.075, 0.945,
        title,
        fontsize=18,
        fontweight="bold",
        color="#0f172a",
    )
    fig.text(
        0.075, 0.905,
        period["full_label"],
        fontsize=10,
        color="#64748b",
    )

    bars = ax.barh(
        labels,
        units,
        height=0.56,
        color="#7c3aed",
        alpha=0.92,
        edgecolor="#6d28d9",
        linewidth=0.7,
        zorder=3,
    )

    max_units = max(units) if units else 0
    right_space = max(max_units * 0.72, 1)

    ax.set_xlim(
        0,
        max_units + right_space if max_units > 0 else 1,
    )

    for index, (bar, quantity, total) in enumerate(zip(bars, units, totals)):
        y = bar.get_y() + bar.get_height() / 2
        ranking = len(units) - index

        if max_units and quantity > max_units * 0.09:
            ax.text(
                max_units * 0.014,
                y,
                f"#{ranking}",
                va="center",
                ha="left",
                fontsize=9,
                fontweight="bold",
                color="#ffffff",
                zorder=4,
            )

        label_x = quantity + (max_units * 0.035 if max_units else 0.1)
        ax.text(
            label_x,
            y + 0.085,
            f"{int(round(quantity))} unidad{'es' if int(round(quantity)) != 1 else ''}",
            va="center",
            ha="left",
            fontsize=10.2,
            fontweight="bold",
            color="#0f172a",
        )
        ax.text(
            label_x,
            y - 0.115,
            f"${total:,.2f} en ventas",
            va="center",
            ha="left",
            fontsize=8.6,
            color="#64748b",
        )

    ax.set_xlabel(
        "Eje X — Total de unidades vendidas",
        fontsize=10.2,
        fontweight="bold",
        color="#475569",
        labelpad=14,
    )
    ax.set_ylabel(
        "Eje Y — Producto",
        fontsize=10.2,
        fontweight="bold",
        color="#475569",
        labelpad=14,
    )

    ax.xaxis.set_major_formatter(_int_formatter())
    ax.grid(axis="x", alpha=0.9)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)

    ax.tick_params(axis="y", length=0, labelsize=9.6, pad=10)
    ax.tick_params(axis="x", labelsize=9)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color("#e2e8f0")

    fig.subplots_adjust(
        left=0.32,
        right=0.95,
        top=0.82,
        bottom=0.17,
    )

    return _figure_to_base64(fig)

# =========================
# INTERPRETACIÓN
# =========================
def _interpretation(
    monthly_rows: list[dict],
    company_rows: list[dict],
    product_rows: list[dict],
    summary: dict,
    company_id: str | None,
) -> list[str]:
    messages: list[str] = []

    sales_count = int(summary.get("sales_count", 0) or 0)
    sales_total = float(summary.get("sales_total", 0) or 0)
    average_ticket = float(summary.get("average_ticket", 0) or 0)

    if sales_count == 0:
        return [
            "No existen ventas pagadas para los filtros seleccionados."
        ]

    messages.append(
        f"En el periodo analizado se registraron {sales_count} ventas pagadas por un importe total de ${sales_total:,.2f}."
    )

    messages.append(
        f"El ticket promedio del periodo es de ${average_ticket:,.2f}."
    )

    if len(monthly_rows) >= 2:
        previous_total = float(monthly_rows[-2].get("sales_total", 0) or 0)
        current_total = float(monthly_rows[-1].get("sales_total", 0) or 0)

        if previous_total > 0:
            change = ((current_total - previous_total) / previous_total) * 100

            if change > 0:
                messages.append(
                    f"Las ventas del último mes aumentaron {abs(change):.1f}% frente al mes anterior."
                )
            elif change < 0:
                messages.append(
                    f"Las ventas del último mes disminuyeron {abs(change):.1f}% frente al mes anterior."
                )
            else:
                messages.append(
                    "Las ventas del último mes se mantuvieron sin variación frente al mes anterior."
                )

    if company_rows and not company_id:
        top_company = company_rows[0]
        messages.append(
            f"La empresa con mayor importe de ventas es {top_company.get('company_name', 'Sin nombre')} con ${float(top_company.get('sales_total', 0) or 0):,.2f}."
        )

    if product_rows:
        top_product = product_rows[0]
        product_name = (
            top_product.get("_id", {}).get("name")
            or top_product.get("_id", {}).get("sku")
            or "Sin nombre"
        )

        messages.append(
            f"El producto con mayor volumen es {product_name}, con {float(top_product.get('units', 0) or 0):,.0f} unidades vendidas."
        )

    return messages


# =========================
# FUNCIÓN PRINCIPAL
# =========================
def generate_developer_matplotlib_analysis(
    database,
    company_id: str | None = None,
    months: int = 6,
) -> dict:
    """
    Genera el análisis visual para el Developer usando ventas pagadas.
    """
    if months not in {0, 3, 6, 12}:
        months = 6

    match = _sales_match(company_id, months)

    monthly_rows = _monthly_sales_data(database, match)
    company_rows = _top_companies_data(database, match)
    product_rows = _top_products_data(database, match)
    summary = _summary_data(database, match)

    period = _period_info(months)
    period_label = period["short_label"]

    return {
        "available": bool(summary["sales_count"]),
        "period_label": period_label,
        "period_range": period["range_label"],
        "period_full_label": period["full_label"],
        "monthly_chart": _monthly_chart(monthly_rows, period),
        "companies_chart": _companies_chart(company_rows, period),
        "products_chart": _products_chart(product_rows, period),
        "summary": summary,
        "interpretation": _interpretation(
            monthly_rows,
            company_rows,
            product_rows,
            summary,
            company_id,
        ),
    }