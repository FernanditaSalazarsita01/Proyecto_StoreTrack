from __future__ import annotations

from .credits import get_credit_summary, get_overdue_customers
from .customers import (
    get_credit_preference_customers,
    get_customer_purchase_profile,
    get_inactive_customers,
    get_preferred_products_by_customer,
    get_top_customers,
)
from .dashboard import build_dashboard
from .products import (
    get_first_to_run_out,
    get_least_sold_products,
    get_low_stock_products,
    get_overstock_products,
    get_product_trends,
    get_restock_recommendations,
    get_slow_moving_products,
    get_top_products,
    get_top_revenue_products,
)
from .query_intents import detect_intent
from .sales import get_best_sales_day, get_largest_sale, get_payment_mix, get_sales_period_summary


def money(value: float) -> str:
    return f"${float(value or 0):,.2f}"


def date_text(value) -> str:
    return value.strftime("%d/%m/%Y") if value else "Sin fecha"


def _result(intent: str, answer: str, rows=None, data_type: str = "none", **extra) -> dict:
    return {"intent": intent, "answer": answer, "data_type": data_type, "rows": rows or [], **extra}


def answer_business_question(db, company_id: str, question: str) -> dict:
    detected = detect_intent(question)
    intent = detected["name"]
    params = detected.get("params", {})
    limit = int(params.get("limit", 5))
    days = int(params.get("days", 60))
    period = params.get("period", "month")
    customer_name = params.get("customer_name", "")

    # PRODUCTOS
    if intent == "top_products":
        rows = get_top_products(db, company_id, days=30, limit=limit)
        if not rows:
            return _result(intent, "No hay ventas suficientes para calcular los productos más vendidos.")
        lines = [f"{i}. {r['name']}: {r['units_sold']} unidades" for i, r in enumerate(rows, 1)]
        return _result(intent, f"Tus {len(rows)} productos más vendidos en los últimos 30 días son:\n" + "\n".join(lines), rows, "ranking")

    if intent == "top_revenue":
        rows = get_top_revenue_products(db, company_id, days=30, limit=limit)
        if not rows:
            return _result(intent, "No hay ventas suficientes para calcular los productos con más ingresos.")
        first = rows[0]
        return _result(intent, f"El producto que más ingresos genera es {first['name']}, con {money(first['revenue'])} en los últimos 30 días.", rows, "ranking")

    if intent == "low_stock":
        rows = get_low_stock_products(db, company_id, limit=limit)
        if not rows:
            return _result(intent, "No encontré productos con stock bajo según su existencia y ritmo de venta.")
        names = ", ".join(f"{r['name']} ({r['stock']} disponibles)" for r in rows[:5])
        return _result(intent, f"Detecté {len(rows)} productos con inventario en riesgo. Los principales son: {names}.", rows, "products")

    if intent == "first_to_run_out":
        rows = get_first_to_run_out(db, company_id, limit=limit)
        if not rows:
            return _result(intent, "No pude estimar qué producto se agotará primero porque no hay consumo reciente suficiente.")
        first = rows[0]
        return _result(intent, f"El producto que podría agotarse primero es {first['name']}. Tiene {first['stock']} unidades y una cobertura aproximada de {first['coverage_days']} días.", rows, "products")

    if intent == "slow_products":
        rows = get_slow_moving_products(db, company_id, inactive_days=days, limit=limit)
        if not rows:
            return _result(intent, f"No encontré productos sin ventas durante al menos {days} días.")
        names = ", ".join(r["name"] for r in rows[:5])
        return _result(intent, f"Encontré {len(rows)} productos sin movimiento durante al menos {days} días: {names}.", rows, "slow_products")

    if intent == "overstock":
        rows = get_overstock_products(db, company_id, limit=limit)
        if not rows:
            return _result(intent, "No detecté productos con exceso claro de inventario.")
        total = sum(r["inventory_value"] for r in rows)
        return _result(intent, f"Detecté {len(rows)} productos con inventario alto o sin consumo reciente. Su valor aproximado es {money(total)}.", rows, "overstock")

    if intent == "idle_inventory_value":
        rows = get_slow_moving_products(db, company_id, inactive_days=days, limit=50)
        total = sum(r["inventory_value"] for r in rows)
        return _result(intent, f"Tienes aproximadamente {money(total)} detenidos en {len(rows)} productos sin movimiento de al menos {days} días.", rows[:limit], "slow_products")

    if intent == "least_sold":
        rows = get_least_sold_products(db, company_id, days=30, limit=limit)
        if not rows:
            return _result(intent, "No encontré productos para comparar.")
        first = rows[0]
        return _result(intent, f"El producto con menos unidades vendidas en los últimos 30 días es {first['name']}, con {first['units_sold']} unidades.", rows, "ranking")

    if intent in ("restock", "purchase_quantities"):
        rows = get_restock_recommendations(db, company_id, limit=limit)
        if not rows:
            return _result(intent, "No detecté productos que requieran reabastecimiento urgente.")
        if intent == "purchase_quantities":
            lines = [f"{r['name']}: comprar aproximadamente {r['suggested_purchase']} unidades" for r in rows]
            answer = "Cantidades sugeridas para cubrir aproximadamente 30 días:\n" + "\n".join(lines)
        else:
            names = ", ".join(r["name"] for r in rows[:5])
            answer = f"Conviene surtir primero: {names}. La prioridad considera stock y ventas de los últimos 30 días."
        return _result(intent, answer, rows, "products")

    if intent in ("products_up", "products_down"):
        direction = "up" if intent == "products_up" else "down"
        rows = get_product_trends(db, company_id, direction=direction, limit=limit)
        if not rows:
            message = "No encontré productos con aumento de ventas." if direction == "up" else "No encontré productos con disminución de ventas."
            return _result(intent, message)
        verb = "aumentaron" if direction == "up" else "disminuyeron"
        return _result(intent, f"Estos productos {verb} sus ventas frente a los 30 días anteriores.", rows, "trends")

    # CLIENTES
    if intent in ("top_customers", "customer_revenue"):
        rows = get_top_customers(db, company_id, days=30, limit=limit, sort_by="total_spent")
        if not rows:
            return _result(intent, "No encontré ventas recientes asociadas a clientes.")
        first = rows[0]
        return _result(intent, f"El cliente que más compra y más ingresos genera es {first['name']}, con {money(first['total_spent'])} en {first['purchases']} compras.", rows, "customers")

    if intent == "frequent_customer":
        rows = get_top_customers(db, company_id, days=365, limit=limit, sort_by="frequency")
        if not rows:
            return _result(intent, "No hay suficientes compras repetidas para calcular frecuencia.")
        first = rows[0]
        return _result(intent, f"El cliente que compra con mayor frecuencia es {first['name']}, aproximadamente cada {first['purchase_frequency_days']} días.", rows, "customers")

    if intent == "highest_avg_ticket_customer":
        rows = get_top_customers(db, company_id, days=365, limit=limit, sort_by="avg_ticket")
        if not rows:
            return _result(intent, "No encontré clientes con ventas para calcular el ticket promedio.")
        first = rows[0]
        return _result(intent, f"El cliente con ticket promedio más alto es {first['name']}, con {money(first['avg_ticket'])} por compra.", rows, "customers")

    if intent in ("customer_profile", "customer_last_purchase", "customer_total_spent"):
        if not customer_name:
            return _result(intent, "Indica el nombre del cliente. Ejemplo: ¿Qué compra normalmente Juan Pérez?")
        profile = get_customer_purchase_profile(db, company_id, customer_name)
        if not profile:
            return _result(intent, f"No encontré ventas para un cliente llamado {customer_name}.")
        if intent == "customer_last_purchase":
            answer = f"La última compra de {profile['name']} fue el {date_text(profile['last_purchase'])}."
        elif intent == "customer_total_spent":
            answer = f"{profile['name']} ha gastado {money(profile['total_spent'])} en {profile['purchases']} compras. Su ticket promedio es {money(profile['avg_ticket'])}."
        else:
            products = ", ".join(x["name"] for x in profile["top_products"][:5]) or "sin detalle de productos"
            answer = f"{profile['name']} compra principalmente: {products}. Ha realizado {profile['purchases']} compras por {money(profile['total_spent'])}."
        return _result(intent, answer, profile["top_products"], "profile", profile=profile)

    if intent == "inactive_customers":
        rows = get_inactive_customers(db, company_id, inactive_days=days, limit=limit)
        if not rows:
            return _result(intent, f"No encontré clientes con {days} días o más sin comprar.")
        return _result(intent, f"Encontré {len(rows)} clientes que llevan al menos {days} días sin comprar.", rows, "inactive_customers")

    if intent == "credit_customers":
        rows = get_credit_preference_customers(db, company_id, limit=limit)
        if not rows:
            return _result(intent, "No encontré clientes que compren principalmente a crédito.")
        return _result(intent, f"Encontré {len(rows)} clientes cuya forma de compra principal es el crédito.", rows, "customers")

    if intent == "preferred_products_by_customer":
        rows = get_preferred_products_by_customer(db, company_id, limit=limit)
        if not rows:
            return _result(intent, "No encontré suficientes compras asociadas a clientes.")
        return _result(intent, "Estos son los productos preferidos de tus principales clientes.", rows, "preferred_products")

    # VENTAS
    if intent in ("sales_period", "sales_count_period", "average_ticket"):
        summary = get_sales_period_summary(db, company_id, period)
        period_name = {"today": "hoy", "week": "esta semana", "month": "este mes", "year": "este año"}.get(period, "este mes")
        if intent == "sales_count_period":
            answer = f"Realizaste {summary['sales_count']} ventas {period_name}."
        elif intent == "average_ticket":
            answer = f"Tu ticket promedio {period_name} es de {money(summary['avg_ticket'])}, calculado con {summary['sales_count']} ventas."
        else:
            answer = f"Vendiste {money(summary['revenue'])} {period_name} en {summary['sales_count']} operaciones."
        return _result(intent, answer, data_type="summary", summary=summary)

    if intent == "largest_sale":
        row = get_largest_sale(db, company_id, period)
        if not row:
            return _result(intent, "No encontré ventas en el periodo seleccionado.")
        return _result(intent, f"La venta más grande fue de {money(row['total'])} para {row['customer_name']} el {date_text(row['created_at'])}.", [row], "sale")

    if intent == "best_sales_day":
        row = get_best_sales_day(db, company_id)
        if not row:
            return _result(intent, "No hay suficientes ventas para identificar el mejor día.")
        return _result(intent, f"Tu mejor día de ventas fue el {row['date']}, con {money(row['revenue'])} en {row['sales_count']} operaciones.", [row], "sale")

    if intent == "payment_mix":
        mix = get_payment_mix(db, company_id, period)
        preferred = "crédito" if mix["credit_revenue"] > mix["cash_revenue"] else "contado"
        answer = (f"En el periodo vendiste {money(mix['cash_revenue'])} de contado y {money(mix['credit_revenue'])} a crédito. "
                  f"La modalidad con mayor ingreso fue {preferred}.")
        return _result(intent, answer, data_type="summary", summary=mix)

    # CRÉDITOS
    if intent == "credit_summary":
        summary = get_credit_summary(db, company_id)
        answer = f"Actualmente tienes {money(summary['pending_balance'])} pendientes de cobro, de los cuales {money(summary['overdue_balance'])} ya están vencidos."
        return _result(intent, answer, data_type="summary", summary=summary)

    if intent in ("overdue", "largest_debtor", "longest_overdue"):
        rows = get_overdue_customers(db, company_id, limit=max(limit, 10))
        if not rows:
            return _result(intent, "No encontré clientes con pagos vencidos.")
        if intent == "largest_debtor":
            rows.sort(key=lambda x: x["balance"], reverse=True)
            first = rows[0]
            answer = f"El cliente con mayor saldo vencido es {first['name']}, con {money(first['balance'])}."
        elif intent == "longest_overdue":
            rows.sort(key=lambda x: x["max_days_overdue"], reverse=True)
            first = rows[0]
            answer = f"El mayor atraso corresponde a {first['name']}, con {first['max_days_overdue']} días y {money(first['balance'])} pendientes."
        else:
            summary = get_credit_summary(db, company_id)
            answer = f"Hay {summary['overdue_customers']} clientes con saldo vencido por {money(summary['overdue_balance'])}."
        return _result(intent, answer, rows[:limit], "credits")

    # RESÚMENES Y RECOMENDACIONES
    if intent in ("summary", "recommendations"):
        dashboard = build_dashboard(db, company_id)
        kpis = dashboard["kpis"]
        if intent == "summary":
            answer = (f"Este mes registraste {kpis['month_sales']} ventas por {money(kpis['month_revenue'])}. "
                      f"Tienes {kpis['low_stock']} productos con inventario en riesgo, {kpis['slow_products']} sin movimiento "
                      f"y {kpis['overdue_customers']} clientes con saldo vencido.")
        else:
            priorities = []
            if kpis["low_stock"]:
                priorities.append(f"reabastecer {kpis['low_stock']} productos")
            if kpis["slow_products"]:
                priorities.append(f"revisar {kpis['slow_products']} productos sin movimiento")
            if kpis["overdue_customers"]:
                priorities.append(f"dar seguimiento a {kpis['overdue_customers']} clientes vencidos")
            answer = "Tus prioridades actuales son: " + "; ".join(priorities) + "." if priorities else "No detecté alertas importantes en este momento."
        return _result(intent, answer, data_type="summary")

    return _result("unknown", (
        "No identifiqué la consulta. Puedes preguntarme por productos, inventario, clientes, ventas o créditos. "
        "Ejemplos: ¿Cuáles son mis 5 productos más vendidos?, ¿Qué clientes llevan 60 días sin comprar? "
        "o ¿Cuánto dinero me deben?"
    ))
