import os
import sys

# Permite `import core` sin importar desde qué directorio se invoque pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# core.py y llm_client.py leen estas variables al importarse (para armar
# los pools de conexión y el cliente de Azure OpenAI). En los tests solo
# se ejercitan funciones puras (nunca se abren los pools ni se llama al
# LLM), así que basta con valores dummy para que el import no falle.
os.environ.setdefault("DSN_DATOS", "postgresql://user:pass@localhost/db_test")
os.environ.setdefault("DSN_CACHE", "postgresql://user:pass@localhost/db_test")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example.invalid")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "test-key")
os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT", "test-deployment")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _sin_almacen_ni_memoria_de_matriz():
    """Los tests no usan la base ni arrastran textos de la Matriz entre sí."""
    import moodle_matriz as mm
    anterior = mm._ALMACEN
    mm._ALMACEN = None
    mm._TEXTOS.clear()
    mm._EN_CURSO.clear()
    yield
    mm._ALMACEN = anterior
    mm._TEXTOS.clear()
    mm._EN_CURSO.clear()
