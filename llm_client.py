"""
llm_client.py
"""

import os
import warnings
import httpx
from openai import AsyncAzureOpenAI

_ssl_verify_disabled = os.environ.get("DISABLE_SSL_VERIFY_DEV_ONLY", "false").lower() == "true"

if _ssl_verify_disabled:
    warnings.warn(
        "DISABLE_SSL_VERIFY_DEV_ONLY está activo: la verificación SSL hacia "
        "Azure OpenAI está DESACTIVADA. Esto es inseguro y solo debe usarse "
        "en desarrollo local. Configura el certificado corporativo real "
        "(setup_certs.py) antes de desplegar a producción.",
        stacklevel=1,
    )
    _http_client = httpx.AsyncClient(verify=False)
else:
    _http_client = None

client = AsyncAzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    http_client=_http_client,
)

DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]
TIMEOUT_VISION_S = float(os.environ.get("TIMEOUT_VISION_S", "180") or 180)


async def generar_texto_narrativo(prompt: str, *, formato_json: bool = False) -> str:
    """
    Envía el prompt a Azure OpenAI y retorna el texto generado. Si
    formato_json=True, fuerza salida JSON válida (response_format
    json_object) -- usado cuando el prompt pide explícitamente un objeto
    JSON como respuesta.
    """
    kwargs = {}
    if formato_json:
        kwargs["response_format"] = {"type": "json_object"}

    response = await client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000,
        temperature=0.4,
        **kwargs,
    )
    return response.choices[0].message.content

async def generar_texto_vision(prompt: str, imagenes: list[str], *, max_tokens: int = 4000) -> str:
    """Envía el prompt con una o varias imágenes (data URLs JPEG/PNG) al
    modelo con visión y retorna el texto. Temperatura 0: se usa para
    transcribir fielmente, no para redactar."""
    contenido = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": u, "detail": "high"}} for u in imagenes
    ]
    response = await client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role": "user", "content": contenido}],
        max_tokens=max_tokens,
        temperature=0,
        timeout=TIMEOUT_VISION_S,   # una página colgada se reintenta en minutos, no en diez
    )
    return response.choices[0].message.content or ""
