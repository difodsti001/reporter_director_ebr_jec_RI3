"""
app.py

Endpoints del Reporte Institucional 3 (cierre reflexivo) para el directivo.
"""

import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
from contextlib import asynccontextmanager, contextmanager

from dotenv import load_dotenv
load_dotenv()

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import core
import moodle_matriz
import ri3

core.configurar_logging(nivel=os.environ.get("LOG_LEVEL", "INFO"))
log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("app_startup")
    await core.abrir_pools()
    yield
    log.info("app_shutdown")
    await core.cerrar_pools()


app = FastAPI(title="Reporte institucional 3 - Cierre reflexivo (EBR)", lifespan=lifespan)

# Dev: permite que el dashboard HTML servido en otro puerto/origen llame a la API.
# Restringir allow_origins a los dominios reales antes de producción.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")


class ReporteRequest(BaseModel):
    userid: int


@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Reporte Institucional 3 (cierre reflexivo)
# ---------------------------------------------------------------------------

@contextmanager
def _errores_ri3(userid: int):
    """Traduce las excepciones de negocio a respuestas HTTP."""
    try:
        yield
    except core.DirectivoNoEncontradoError:
        raise HTTPException(404, f"No se encontró IE asociada al userid {userid}")
    except core.NoEsDirectivoError:
        raise HTTPException(403, "Este reporte está disponible únicamente para el directivo de la institución.")
    except ri3.ProgramaNoSoportadoError:
        raise HTTPException(403, "Este reporte no está disponible para el programa de la institución.")
    except moodle_matriz.MatrizNoDisponibleError:
        log.error("endpoint_ri3_moodle_no_disponible", userid=userid, exc_info=True)
        raise HTTPException(503, "No fue posible consultar la Matriz en este momento. Intente nuevamente más tarde.")
    except HTTPException:
        raise
    except Exception:
        log.error("endpoint_ri3_error_no_manejado", userid=userid, exc_info=True)
        raise HTTPException(500, "Error interno al procesar el reporte")


@app.get("/reporte_director_ri3", response_class=HTMLResponse)
async def reporte_ri3_dashboard(request: Request):
    return templates.TemplateResponse(request, "index_ri3.html")


@app.get("/reporte_ri3/consultar")
async def consultar_ri3(userid: int):
    """Solo lectura (sin LLM): RI3 vigente (accion=mostrar) o estado de las
    fuentes para solicitarlo (accion=generar)."""
    with _errores_ri3(userid):
        return await ri3.consultar_ri3(userid)


@app.post("/reporte_ri3/generar")
async def generar_ri3(payload: ReporteRequest, courseid: int, cmid: int):
    with _errores_ri3(payload.userid):
        return await ri3.obtener_o_generar_ri3(payload.userid, courseid, cmid)
