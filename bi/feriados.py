"""Feriados nacionales de Argentina (inamovibles + trasladables y puentes publicados)."""

from datetime import date

INAMOVIBLES = [(1, 1), (3, 24), (4, 2), (5, 1), (5, 25), (6, 20), (7, 9), (12, 8), (12, 25)]

# Carnaval, Semana Santa, trasladables y días no laborables con fines turísticos, por año.
MOVILES = {
    2023: [
        "2023-02-20",
        "2023-02-21",
        "2023-04-06",
        "2023-04-07",
        "2023-05-26",
        "2023-06-17",
        "2023-06-19",
        "2023-08-21",
        "2023-10-13",
        "2023-10-16",
        "2023-11-20",
    ],
    2024: [
        "2024-02-12",
        "2024-02-13",
        "2024-03-28",
        "2024-03-29",
        "2024-04-01",
        "2024-06-17",
        "2024-06-21",
        "2024-08-17",
        "2024-10-11",
        "2024-11-18",
    ],
    2025: [
        "2025-03-03",
        "2025-03-04",
        "2025-04-17",
        "2025-04-18",
        "2025-05-02",
        "2025-06-16",
        "2025-08-15",
        "2025-08-17",
        "2025-10-12",
        "2025-11-21",
        "2025-11-24",
    ],
    2026: [
        "2026-02-16",
        "2026-02-17",
        "2026-03-23",
        "2026-04-02",
        "2026-04-03",
        "2026-06-15",
        "2026-07-10",
        "2026-08-17",
        "2026-10-12",
        "2026-11-23",
        "2026-12-07",
    ],
    2027: [
        "2027-02-08",
        "2027-02-09",
        "2027-03-25",
        "2027-03-26",
        "2027-06-17",
        "2027-08-16",
        "2027-10-11",
        "2027-11-22",
    ],
}


def feriados(anio):
    fijos = {date(anio, m, d) for m, d in INAMOVIBLES}
    return fijos | {date.fromisoformat(f) for f in MOVILES.get(anio, [])}


_cache = {}


def es_feriado(fecha):
    if fecha.year not in _cache:
        _cache[fecha.year] = feriados(fecha.year)
    return fecha in _cache[fecha.year]


def es_fin_de_semana_largo(fecha):
    """Feriado o día pegado a un feriado que forma fin de semana largo."""
    from datetime import timedelta

    for delta in (-2, -1, 0, 1, 2):
        d = fecha + timedelta(days=delta)
        if es_feriado(d) and d.weekday() in (0, 4):
            return True
    return es_feriado(fecha)
