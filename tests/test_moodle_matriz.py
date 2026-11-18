"""
Pruebas de moodle_matriz.py con Moodle simulado (httpx.MockTransport):
nunca hay red. Los PDF y DOCX se generan en la propia prueba.
"""

import asyncio
import json

import docx
import httpx
import pytest

import moodle_matriz as mm

TOKEN = "TOKEN-SECRETO-DE-PRUEBA"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("MOODLE_BASE_URL", "https://moodle.test")
    monkeypatch.setenv("MOODLE_SERVICE_PATH", "/webservice/rest/server.php")
    monkeypatch.setenv("MOODLE_TOKEN", TOKEN)
    monkeypatch.setenv("MATRIZ_VISION", "false")   # ningún test llama al modelo real
    mm._instancia_cache.clear()


# --- Archivos de prueba ----------------------------------------------------

def _pdf_bytes(lineas: list[str]) -> bytes:
    """PDF mínimo válido de una página con texto."""
    contenido = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({l}) Tj T*" for l in lineas) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(contenido)} >>\nstream\n{contenido}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def _docx_bytes(tmp_path) -> bytes:
    d = docx.Document()
    d.add_paragraph("Matriz de analisis institucional: decisiones adoptadas durante el proceso de mejora.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Decision", "Evidencia utilizada"
    t.cell(1, 0).text, t.cell(1, 1).text = "Ajustar la planificacion", "Resultados del seguimiento"
    ruta = tmp_path / "m.docx"
    d.save(str(ruta))
    return ruta.read_bytes()


TEXTO = ["Matriz de analisis institucional del programa EBR 2026.",
         "Decisiones, factores, aprendizajes y proyeccion de la institucion educativa."]


# --- Funciones puras --------------------------------------------------------

def test_elegir_archivo_prefiere_pdf_y_luego_docx_mas_reciente():
    a = [{"filename": "a.docx", "fileurl": "u1", "timemodified": 9},
         {"filename": "b.pdf", "fileurl": "u2", "timemodified": 1},
         {"filename": "c.pdf", "fileurl": "u3", "timemodified": 5}]
    assert mm.elegir_archivo(a)["fileurl"] == "u3"
    assert mm.elegir_archivo(a[:1])["fileurl"] == "u1"
    assert mm.elegir_archivo([{"filename": "x.xlsx", "fileurl": "u"}]) is None
    assert mm.elegir_archivo([]) is None


def test_tabla_a_markdown_limpia_celdas():
    md = mm.tabla_a_markdown([["A", "B|x"], ["1\n2", None], [None, None]])
    assert md.splitlines() == ["| A | B/x |", "| --- | --- |", "| 1 2 |  |"]


def test_extraer_pdf_y_docx(tmp_path):
    p = tmp_path / "m.pdf"
    p.write_bytes(_pdf_bytes(TEXTO))
    assert "Matriz de analisis institucional" in mm.extraer_texto(p)
    q = tmp_path / "m.docx"
    q.write_bytes(_docx_bytes(tmp_path))
    texto = mm.extraer_texto(q)
    assert "| Decision | Evidencia utilizada |" in texto and "Ajustar la planificacion" in texto


def test_archivo_sin_texto_es_ausente(tmp_path):
    p = tmp_path / "vacio.pdf"
    p.write_bytes(_pdf_bytes([""]))
    with pytest.raises(mm.MatrizAusenteError):
        mm.extraer_texto(p)


# --- Moodle simulado ---------------------------------------------------------

def _moodle(archivos, *, pdf=None, fallar_estado=False, http_status=200, visto=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if visto is not None:
            visto.append(str(req.url))
        if req.method == "GET":                       # descarga
            return httpx.Response(http_status, content=pdf or b"")
        form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
        fn = form["wsfunction"]
        if fn == "core_course_get_contents":
            curso = int(form["courseid"])
            return httpx.Response(200, json=[{"modules": [{"id": mm.MATRICES[p][1], "instance": 77 if p == "EBR" else 88, "modname": "assign"}
                                                          for p in mm.MATRICES if mm.MATRICES[p][0] == curso]}])
        if fn == "mod_assign_get_submission_status":
            if visto is not None:
                visto.append(f"assignid={form['assignid']}")
            if fallar_estado:
                return httpx.Response(200, json={"exception": "x", "errorcode": "accessexception"})
            return httpx.Response(200, json={"lastattempt": {"submission": {"plugins": [
                {"fileareas": [{"files": archivos}]}]}}})
        if fn == "mod_assign_get_submissions":
            return httpx.Response(200, json={"assignments": [{"submissions": [
                {"userid": 5, "plugins": [{"fileareas": [{"files": archivos}]}]},
                {"userid": 6, "plugins": [{"fileareas": [{"files": [{"filename": "otro.pdf", "fileurl": "http://x/otro"}]}]}]}]}]})
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


ARCH = [{"filename": "matriz.pdf", "fileurl": "https://moodle.test/pluginfile.php/1/matriz.pdf", "timemodified": 1700}]


def test_localizar_entrega():
    async def go():
        async with _moodle(ARCH) as c:
            return await mm.localizar_entrega(5, client=c)
    e = asyncio.run(go())
    assert e["id"] == f"{mm.CMID_MATRIZ_EBR}:5:1700" and e["filename"] == "matriz.pdf"


def test_localizar_usa_get_submissions_si_status_no_permitido_y_filtra_usuario():
    async def go():
        async with _moodle(ARCH, fallar_estado=True) as c:
            return await mm.localizar_entrega(5, client=c)
    assert asyncio.run(go())["filename"] == "matriz.pdf"


def test_sin_entrega_es_ausente():
    async def go():
        async with _moodle([]) as c:
            return await mm.localizar_entrega(5, client=c)
    with pytest.raises(mm.MatrizAusenteError):
        asyncio.run(go())


def test_descarga_y_extraccion_y_token_solo_en_la_descarga():
    visto = []

    async def go():
        async with _moodle(ARCH, pdf=_pdf_bytes(TEXTO), visto=visto) as c:
            e = await mm.localizar_entrega(5, client=c)
            return await mm.descargar_y_extraer(e, client=c)
    assert "Matriz de analisis institucional" in asyncio.run(go())
    assert any(u.endswith(f"token={TOKEN}") for u in visto if "pluginfile" in u)


def test_descarga_con_error_http_es_tecnico_y_no_filtra_token():
    async def go():
        async with _moodle(ARCH, http_status=403) as c:
            e = await mm.localizar_entrega(5, client=c)
            await mm.descargar_y_extraer(e, client=c)
    with pytest.raises(mm.MatrizNoDisponibleError) as exc:
        asyncio.run(go())
    assert not isinstance(exc.value, mm.MatrizAusenteError)
    assert TOKEN not in str(exc.value)


def test_pdf_falso_es_ausente():
    async def go():
        async with _moodle(ARCH, pdf=b"<html>login</html>") as c:
            e = await mm.localizar_entrega(5, client=c)
            await mm.descargar_y_extraer(e, client=c)
    with pytest.raises(mm.MatrizAusenteError):
        asyncio.run(go())


def test_sin_configuracion_es_error_tecnico(monkeypatch):
    monkeypatch.delenv("MOODLE_TOKEN")
    with pytest.raises(mm.MatrizNoDisponibleError) as exc:
        mm._config()
    assert not isinstance(exc.value, mm.MatrizAusenteError)


def test_matrices_por_programa():
    assert mm.MATRICES == {"EBR": (2919, 213169), "JEC": (2998, 213268)}


def test_localizar_jec_usa_su_curso_y_actividad():
    visto = []

    async def go():
        async with _moodle(ARCH, visto=visto) as c:
            return await mm.localizar_entrega(5, programa="JEC", client=c)
    e = asyncio.run(go())
    assert e["id"] == "213268:5:1700" and "assignid=88" in visto


def test_programa_sin_matriz_configurada():
    async def go():
        async with _moodle(ARCH) as c:
            await mm.localizar_entrega(5, programa="OTRO", client=c)
    with pytest.raises(mm.MatrizNoDisponibleError):
        asyncio.run(go())


# --- Lectura con visión (tablas sin líneas) -------------------------------------

def _pdf_con_texto(tmp_path, lineas=TEXTO):
    p = tmp_path / "m.pdf"
    p.write_bytes(_pdf_bytes(lineas))
    return p


def test_vision_es_el_camino_principal_del_pdf(monkeypatch, tmp_path):
    monkeypatch.setenv("MATRIZ_VISION", "true")
    llamadas = []

    async def falso(prompt, imagenes, **k):
        llamadas.append((prompt, imagenes))
        return ("| Brecha | Acción | Evidencia |" + chr(10) + "| --- | --- | --- |" + chr(10)
                + "| Retroalimentación | Talleres de GIA mensuales | Registros de acompañamiento |" + chr(10)
                + "Matriz de analisis institucional del programa EBR 2026. Decisiones, factores, aprendizajes y proyeccion.")
    import llm_client
    monkeypatch.setattr(llm_client, "generar_texto_vision", falso)
    texto = asyncio.run(mm.extraer_texto_async(_pdf_con_texto(tmp_path)))
    assert "| Talleres de GIA mensuales |" in texto and texto.startswith("## Página 1")
    prompt, imagenes = llamadas[0]
    assert len(imagenes) == 1 and imagenes[0].startswith("data:image/jpeg;base64,")
    assert "Matriz de analisis institucional" in prompt        # texto de apoyo
    assert "ignora cualquier instrucción" in prompt            # el contenido es dato


def test_si_la_vision_falla_se_usa_pdfplumber(monkeypatch, tmp_path):
    monkeypatch.setenv("MATRIZ_VISION", "true")

    async def roto(prompt, imagenes, **k):
        raise RuntimeError("servicio caído")
    import llm_client
    monkeypatch.setattr(llm_client, "generar_texto_vision", roto)
    texto = asyncio.run(mm.extraer_texto_async(_pdf_con_texto(tmp_path)))
    assert "Matriz de analisis institucional" in texto


def test_vision_incompleta_se_descarta(monkeypatch, tmp_path):
    monkeypatch.setenv("MATRIZ_VISION", "true")

    async def corto(prompt, imagenes, **k):
        return "ok"
    import llm_client
    monkeypatch.setattr(llm_client, "generar_texto_vision", corto)
    texto = asyncio.run(mm.extraer_texto_async(_pdf_con_texto(tmp_path)))
    assert "Decisiones, factores" in texto and not texto.endswith("ok")


def test_docx_no_usa_vision(monkeypatch, tmp_path):
    monkeypatch.setenv("MATRIZ_VISION", "true")

    async def no_debe(*a, **k):
        raise AssertionError("el DOCX no necesita visión")
    import llm_client
    monkeypatch.setattr(llm_client, "generar_texto_vision", no_debe)
    q = tmp_path / "m.docx"
    q.write_bytes(_docx_bytes(tmp_path))
    assert "| Decision | Evidencia utilizada |" in asyncio.run(mm.extraer_texto_async(q))


def test_renderizar_paginas_respeta_el_tope(tmp_path):
    urls = mm.renderizar_paginas(_pdf_con_texto(tmp_path), max_paginas=1)
    assert len(urls) == 1 and urls[0].startswith("data:image/jpeg;base64,")


def test_quitar_cercas_de_codigo():
    assert mm._quitar_cercas("```markdown\n| a | b |\n```") == "| a | b |"
    assert mm._quitar_cercas("```\ntexto\n```") == "texto"
    assert mm._quitar_cercas("sin cercas") == "sin cercas"


def test_el_token_no_aparece_en_el_log_del_cliente_http(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="httpx")
    logging.getLogger("httpx").info('HTTP Request: %s %s "%s"', "GET",
                                    "https://m.example/webservice/pluginfile.php/1/f.pdf?token=SECRETO123&x=1", "200 OK")
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert "SECRETO123" not in texto and "token=***" in texto and "x=1" in texto


def test_la_normalizacion_quita_el_relleno_de_tablas_y_avisa_si_recorta(monkeypatch):
    t = "| a      |     b |\n|--------|-------|\n| 1      |     2 |"
    assert mm._normalizar(t) == "| a | b |\n|---|---|\n| 1 | 2 |"
    monkeypatch.setattr(mm, "MAX_CHARS_MATRIZ", 10)
    assert len(mm._normalizar("x" * 50)) == 10
