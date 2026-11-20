"""
core.py

Infraestructura compartida del servicio de Reporte Institucional 3 (RI3):
logging, excepciones de negocio, pools de conexión y resolución de la IE
del directivo.

Dos bases de datos, dos pools separados:
- pool_datos:  base con public."base_ebr_IA"
- pool_cache:  base con f4_reportes_directivo y f4_consultas_directivo
               (tablas compartidas con RI1 y RI2; se distinguen por tipo_reporte)

La lógica del RI1 y del RI2 vive en sus propios servicios: aquí no se
calcula ni se genera ninguno de los dos.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

import structlog
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


# =============================================================================
# Logging estructurado
# =============================================================================

def configurar_logging(nivel: str = "INFO") -> None:
    """Llamar UNA VEZ al arrancar la aplicación, antes de loguear nada."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, nivel.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, nivel.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger(__name__)


# =============================================================================
# Excepciones de negocio
# =============================================================================

class DirectivoNoEncontradoError(Exception):
    """El userid no resuelve a ninguna IE en base_ebr_IA."""


class NoEsDirectivoError(Exception):
    """El userid existe en base_ebr_IA pero su cargo no es DIRECTIVO: el
    reporte institucional solo lo ve el directivo."""


# =============================================================================
# Configuración de conexión
# =============================================================================

_KEEPALIVE_PARAMS = "keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=3"


def _con_keepalives(dsn: str) -> str:
    separador = "&" if "?" in dsn else "?"
    return f"{dsn}{separador}{_KEEPALIVE_PARAMS}"


DSN_DATOS = _con_keepalives(os.environ["DSN_DATOS"])
DSN_CACHE = _con_keepalives(os.environ["DSN_CACHE"])

_MAX_IDLE = int(os.environ.get("POOL_MAX_IDLE_SECONDS", "300"))

_POOL_KWARGS = dict(
    min_size=1,
    max_size=10,
    kwargs={"row_factory": dict_row},
    open=False,
    max_idle=_MAX_IDLE,
    check=AsyncConnectionPool.check_connection,
)

pool_datos = AsyncConnectionPool(conninfo=DSN_DATOS, **_POOL_KWARGS)
pool_cache = AsyncConnectionPool(conninfo=DSN_CACHE, **_POOL_KWARGS)


async def abrir_pools() -> None:
    """Llamar en el evento startup de FastAPI."""
    await pool_datos.open()
    await pool_cache.open()
    await _asegurar_schema_cache()


async def cerrar_pools() -> None:
    """Llamar en el evento shutdown de FastAPI."""
    await pool_datos.close()
    await pool_cache.close()


async def _asegurar_schema_cache() -> None:
    """Crea las tablas de caché si no existen (entornos nuevos). En
    producción las tablas ya existen -- compartidas con RI1, con la columna
    tipo_reporte y las restricciones UNIQUE (cod_modular, tipo_reporte) y
    UNIQUE (cod_modular, userid_directivo, tipo_reporte) -- y esto no
    modifica nada."""
    ddl = """
        CREATE TABLE IF NOT EXISTS f4_reportes_directivo (
            id SERIAL PRIMARY KEY,
            cod_modular VARCHAR NOT NULL,
            estado VARCHAR NOT NULL DEFAULT 'generado',
            n_docentes_evaluados INTEGER NOT NULL,
            reporte_json JSONB,
            fecha_generacion TIMESTAMP NOT NULL DEFAULT now(),
            fecha_actualizacion TIMESTAMP NOT NULL DEFAULT now(),
            tipo_reporte VARCHAR,
            CONSTRAINT chk_estado CHECK (estado IN ('generado', 'muestra_insuficiente', 'sin_datos')),
            CONSTRAINT chk_reporte_json_si_generado
                CHECK (estado <> 'generado' OR reporte_json IS NOT NULL),
            CONSTRAINT uq_cod_modular_tipo_reporte UNIQUE (cod_modular, tipo_reporte)
        );

        CREATE TABLE IF NOT EXISTS f4_consultas_directivo (
            id SERIAL PRIMARY KEY,
            cod_modular VARCHAR NOT NULL,
            userid_directivo INTEGER NOT NULL,
            courseid INTEGER NOT NULL,
            cmid INTEGER NOT NULL,
            id_reporte_directivo INTEGER NOT NULL REFERENCES f4_reportes_directivo(id),
            fecha_consulta TIMESTAMP NOT NULL DEFAULT now(),
            tipo_reporte VARCHAR,
            CONSTRAINT uq_cod_modular_userid_tipo UNIQUE (cod_modular, userid_directivo, tipo_reporte)
        );

        CREATE INDEX IF NOT EXISTS idx_consultas_cod_modular ON f4_consultas_directivo (cod_modular);
        CREATE INDEX IF NOT EXISTS idx_consultas_userid ON f4_consultas_directivo (userid_directivo);
        CREATE INDEX IF NOT EXISTS idx_consultas_reporte ON f4_consultas_directivo (id_reporte_directivo);
    """
    async with pool_cache.connection() as conn:
        await conn.execute(ddl)
        await conn.commit()


# =============================================================================
# Configuración de negocio
# =============================================================================

# Solo el directivo puede ver el reporte institucional (base_ebr_IA.cargo).
CARGO_DIRECTIVO = "DIRECTIVO"

NIVELES_EDUCATIVOS = ("Inicial", "Primaria", "Secundaria")


# =============================================================================
# Resolución de la IE del directivo
# =============================================================================

def _armar_clave_ie(cod_institucional: Optional[str], nombre_ie: Optional[str],
                    ugel: Optional[str], region: Optional[str], distrito: Optional[str]) -> str:
    """Clave de la IE en la caché. Preferentemente el cod_institucional; si
    es null o vacío, la clave compuesta nombre|ugel|región|distrito."""
    cod = (cod_institucional or "").strip()
    if cod:
        return cod
    return "|".join([nombre_ie or "", ugel or "", region or "", distrito or ""])


def _elegir_fila_directivo(rows: list[dict], userid: int) -> dict:
    """De las filas de base_ebr_IA del userid elige la del directivo.
    Lanza DirectivoNoEncontradoError si el userid no existe y
    NoEsDirectivoError si existe pero su cargo no es DIRECTIVO."""
    if not rows:
        log.warning("directivo_no_encontrado", userid=userid)
        raise DirectivoNoEncontradoError(f"userid {userid} no tiene IE asociada")
    for r in rows:
        if (r.get("cargo") or "").strip().upper() == CARGO_DIRECTIVO:
            return r
    log.warning("acceso_denegado_no_es_directivo", userid=userid)
    raise NoEsDirectivoError(f"userid {userid} no tiene cargo {CARGO_DIRECTIVO}")


async def resolver_ie(userid: int) -> dict:
    """Busca la IE del directivo por userid y valida que su cargo en
    base_ebr_IA sea DIRECTIVO. Retorna la clave de la IE ("clave_ie":
    cod_institucional o, si no hay, nombre|ugel|región|distrito) más los
    campos necesarios para filtrar a sus docentes."""
    query = """
        SELECT cod_institucional, nombre_ie, ugel, "región" AS region, distrito, cargo
        FROM public."base_ebr_IA"
        WHERE userid = %(userid)s
    """
    async with pool_datos.connection() as conn:
        rows = await (await conn.execute(query, {"userid": userid})).fetchall()

    row = _elegir_fila_directivo(rows, userid)
    cod = (row["cod_institucional"] or "").strip()
    clave_ie = _armar_clave_ie(cod, row["nombre_ie"], row["ugel"], row["region"], row["distrito"])
    log.info(
        "ie_resuelta",
        userid=userid,
        clave_ie=clave_ie,
        por_cod_institucional=bool(cod),
        nombre_ie=row["nombre_ie"],
    )
    return {
        "clave_ie": clave_ie,
        "cod_institucional": cod or None,
        "nombre_ie": row["nombre_ie"],
        "ugel": row["ugel"],
        "region": row["region"],
        "distrito": row["distrito"],
    }
