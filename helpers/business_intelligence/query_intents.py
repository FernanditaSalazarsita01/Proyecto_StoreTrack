from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFD", str(text or "").lower())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = re.sub(r"[^a-z0-9$%\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_limit(text: str, default: int = 5) -> int:
    q = normalize(text)
    patterns = [
        r"(?:dame|muestra|lista|cuales son|mis)\s+(?:los|las|mis)?\s*(\d{1,2})\s+(?:productos|clientes|ventas|creditos)",
        r"(?:top|primeros|principales)\s+(\d{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, q)
        if match:
            return max(1, min(int(match.group(1)), 50))
    return default


def extract_days(text: str, default: int = 60) -> int:
    q = normalize(text)
    match = re.search(r"\b(\d{1,4})\s+dias?\b", q)
    return max(1, min(int(match.group(1)), 3650)) if match else default


def extract_period(text: str) -> str:
    q = normalize(text)
    if any(x in q for x in ("hoy", "dia de hoy")):
        return "today"
    if any(x in q for x in ("esta semana", "semana actual", "ultimos 7 dias")):
        return "week"
    if any(x in q for x in ("este mes", "mes actual", "ultimos 30 dias")):
        return "month"
    if any(x in q for x in ("este ano", "ano actual")):
        return "year"
    return "month"


def extract_customer_name(question: str) -> str:
    clean = str(question or "").strip().rstrip("?.!")
    patterns = [
        r"(?:qu[eé] compra normalmente|qu[eé] suele comprar|qu[eé] productos compra|producto prefiere)\s+(.+)$",
        r"(?:cu[aá]ndo fue la [uú]ltima compra de|[uú]ltima compra de|cu[aá]nto ha gastado|cu[aá]nto gast[oó]|saldo de|deuda de)\s+(.+)$",
        r"(?:cliente|sobre el cliente|sobre)\s+(.+)$",
        r"(?:de|para)\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚáéíóúÑñ .'-]{1,80})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .?")
            value = re.sub(r"^(el|la|cliente)\s+", "", value, flags=re.IGNORECASE)
            if len(value) >= 2:
                return value
    return ""


PATTERNS: dict[str, list[str]] = {
    "summary": ["resumen de mi negocio", "resumen de mi empresa", "como va mi negocio", "como va mi empresa", "analisis general"],
    "recommendations": ["que problemas debo atender", "que debo atender primero", "dame recomendaciones", "como puedo mejorar"],
    "sales_period": ["cuanto vendi", "ventas de hoy", "ventas esta semana", "ventas este mes", "ingresos del mes"],
    "sales_count_period": ["cuantas ventas hice", "numero de ventas", "operaciones de venta"],
    "average_ticket": ["ticket promedio", "promedio por venta", "venta promedio"],
    "largest_sale": ["venta mas grande", "venta de mayor monto", "mayor venta"],
    "best_sales_day": ["mejor dia de ventas", "dia vendo mas", "dia con mas ventas"],
    "payment_mix": ["cuanto vendi a credito", "cuanto vendi de contado", "forma de pago se usa mas", "ventas a credito y contado"],

    "top_products": ["productos mas vendidos", "producto mas vendido", "que se vende mas", "que vendo mas", "producto que mas sale", "articulos mas populares"],
    "top_revenue": ["producto genera mas ingresos", "producto genera mas dinero", "mayor ingreso por producto", "producto mas rentable por ventas"],
    "low_stock": ["stock bajo", "pocas existencias", "poco inventario", "se esta acabando", "se estan acabando", "por agotarse"],
    "first_to_run_out": ["producto se agotara primero", "cual se acaba primero", "que producto se terminara primero"],
    "slow_products": ["productos no se han vendido", "sin ventas", "sin movimiento", "casi no se venden", "baja rotacion", "inventario detenido"],
    "overstock": ["demasiado inventario", "exceso de inventario", "sobrestock", "muchas existencias"],
    "idle_inventory_value": ["dinero detenido", "dinero inmovilizado", "valor de productos sin movimiento", "capital detenido"],
    "least_sold": ["producto ha vendido menos", "producto menos vendido", "que se vende menos"],
    "restock": ["deberia volver a surtir", "que debo surtir", "reabastecer", "resurtir", "que debo comprar"],
    "purchase_quantities": ["cuanto debo comprar", "cuantas piezas debo comprar", "cantidad a surtir", "compra sugerida"],
    "products_up": ["productos aumentaron sus ventas", "subieron sus ventas", "crecieron sus ventas"],
    "products_down": ["productos disminuyeron sus ventas", "bajaron sus ventas", "cayeron sus ventas"],

    "top_customers": ["cliente compra mas", "mejores clientes", "quien compra mas", "cliente principal", "quien gasta mas"],
    "customer_revenue": ["cliente genera mas ingresos", "cliente deja mas dinero", "cliente con mayor gasto"],
    "frequent_customer": ["cliente compra con mayor frecuencia", "cliente compra mas seguido", "cliente mas frecuente"],
    "highest_avg_ticket_customer": ["cliente tiene ticket promedio mas alto", "cliente con mayor ticket promedio"],
    "customer_profile": ["que compra normalmente", "que suele comprar", "que productos compra", "producto prefiere"],
    "customer_last_purchase": ["cuando fue la ultima compra", "ultima compra de"],
    "customer_total_spent": ["cuanto ha gastado", "cuanto gasto", "total comprado por"],
    "inactive_customers": ["clientes dejaron de comprar", "clientes sin comprar", "clientes inactivos"],
    "credit_customers": ["clientes compran principalmente a credito", "clientes que compran a credito", "preferencia de credito"],
    "preferred_products_by_customer": ["producto prefiere cada cliente", "preferencias de cada cliente", "que compra cada cliente"],

    "credit_summary": ["cuanto dinero me deben", "saldo pendiente", "cartera pendiente", "dinero por cobrar"],
    "overdue": ["pagos vencidos", "creditos vencidos", "quien no ha pagado", "quien debe", "clientes atrasados"],
    "largest_debtor": ["cliente debe mas", "mayor deudor", "quien me debe mas"],
    "longest_overdue": ["quien tiene mas dias de atraso", "mayor atraso", "mas dias sin pagar"],
}


def _score(text: str, pattern: str) -> float:
    if pattern in text:
        return 2.0 + len(pattern.split()) * 0.03
    text_words = set(text.split())
    pattern_words = set(pattern.split())
    overlap = len(text_words & pattern_words) / max(len(pattern_words), 1)
    similarity = SequenceMatcher(None, text, pattern).ratio()
    return overlap * 0.9 + similarity * 0.35


def detect_intent(question: str) -> dict:
    q = normalize(question)
    params = {
        "limit": extract_limit(question, 5),
        "days": extract_days(question, 60),
        "period": extract_period(question),
        "customer_name": extract_customer_name(question),
    }

    # Reglas prioritarias para evitar ambigüedad.
    if (("dinero" in q or "capital" in q) and any(x in q for x in ("detenido", "inmovilizado", "sin movimiento"))):
        return {"name": "idle_inventory_value", "params": params, "score": 2.5}
    if "cada cliente" in q and any(x in q for x in ("prefiere", "compra")):
        return {"name": "preferred_products_by_customer", "params": params, "score": 2.5}
    if "30 dias" in q and any(x in q for x in ("no se", "sin venta", "sin movimiento")):
        params["days"] = 30
        return {"name": "slow_products", "params": params, "score": 2.5}
    if "60 dias" in q and any(x in q for x in ("no se", "sin venta", "sin movimiento")):
        params["days"] = 60
        return {"name": "slow_products", "params": params, "score": 2.5}
    if "60 dias" in q and "cliente" in q and "sin comprar" in q:
        params["days"] = 60
        return {"name": "inactive_customers", "params": params, "score": 2.5}

    best_name = "unknown"
    best_score = 0.0
    for name, patterns in PATTERNS.items():
        for pattern in patterns:
            current = _score(q, pattern)
            if current > best_score:
                best_name = name
                best_score = current

    if best_score < 0.58:
        best_name = "unknown"

    return {"name": best_name, "params": params, "score": round(best_score, 3)}
