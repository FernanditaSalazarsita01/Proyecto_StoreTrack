import extensions as ext


def main():
    ext.init_mongo()
    db = ext.db

    print("====================================")
    print("RESUMEN GENERAL")
    print("====================================")

    print("Empresas:", db["companies"].count_documents({}))
    print("Clientes:", db["clients"].count_documents({}))
    print("Ventas:", db["sales"].count_documents({}))

    sales_with_client = db["sales"].count_documents({
        "customer.client_id": {
            "$exists": True,
            "$nin": [None, ""]
        }
    })

    print("Ventas con cliente identificado:", sales_with_client)

    customer_ids = db["sales"].distinct(
        "customer.client_id",
        {
            "customer.client_id": {
                "$exists": True,
                "$nin": [None, ""]
            }
        }
    )

    print("Clientes con al menos una venta:", len(customer_ids))

    print()
    print("====================================")
    print("HISTORIAL POR CLIENTE")
    print("====================================")

    pipeline = [
        {
            "$match": {
                "customer.client_id": {
                    "$exists": True,
                    "$nin": [None, ""]
                }
            }
        },
        {
            "$group": {
                "_id": "$customer.client_id",
                "total_ventas": {
                    "$sum": 1
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "clientes": {
                    "$sum": 1
                },
                "promedio_ventas_por_cliente": {
                    "$avg": "$total_ventas"
                },
                "maximo_ventas_cliente": {
                    "$max": "$total_ventas"
                },
                "minimo_ventas_cliente": {
                    "$min": "$total_ventas"
                }
            }
        }
    ]

    result = list(db["sales"].aggregate(pipeline))

    if result:
        stats = result[0]

        print("Clientes analizados:", stats.get("clientes", 0))
        print(
            "Promedio de ventas por cliente:",
            round(stats.get("promedio_ventas_por_cliente", 0), 2)
        )
        print(
            "Máximo de ventas de un cliente:",
            stats.get("maximo_ventas_cliente", 0)
        )
        print(
            "Mínimo de ventas de un cliente:",
            stats.get("minimo_ventas_cliente", 0)
        )
    else:
        print("No existen ventas con clientes identificados.")

    print()
    print("Análisis finalizado.")


if __name__ == "__main__":
    main()