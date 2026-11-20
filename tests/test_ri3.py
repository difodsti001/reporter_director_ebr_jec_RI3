"""
Pruebas del Reporte Institucional 3 (F4 - EBR 2026).

Solo funciones puras y la generación con el LLM simulado: nunca se abren
los pools ni se llama a Azure OpenAI. Casos de la Adenda (sec. 10 y 14):
RI3-03, RI3-04, RI3-05 (parcial), CP26 y CP27.
"""

import asyncio
import copy
import json
import re
from datetime import datetime, timezone

import pytest

import ri3


def _fila(id_, estado_cob, **extra):
    return {
        "id": id_,
        "reporte_json": {"estado_cobertura": estado_cob, "fecha_generacion": "2026-11-01T10:00:00+00:00",
                         "sintesis_institucional": "Texto de síntesis previo.", **extra},
        "fecha_generacion": datetime(2026, 11, 1, tzinfo=timezone.utc),
        "fecha_actualizacion": datetime(2026, 11, 2, tzinfo=timezone.utc),
    }


IE = {"clave_ie": "IE-1", "nombre_ie": "IE de prueba", "programa": "EBR"}
IE_JEC = {**IE, "programa": "JEC"}


# --- Herencia de cobertura (Adenda RI3-03/04) ------------------------------

def test_tratamiento_segun_cobertura():
    assert ri3.tratamiento_fuente(None) == ri3.TRAT_AUSENTE
    assert ri3.tratamiento_fuente({"estado_cobertura": "COB_SUFICIENTE"}) == ri3.TRAT_USAR
    assert ri3.tratamiento_fuente({"estado_cobertura": "COB_BAJO_UMBRAL"}) == ri3.TRAT_HIPOTESIS
    assert ri3.tratamiento_fuente({"estado_cobertura": "COB_CONFIDENCIAL"}) == ri3.TRAT_EXCLUIR
    # sin estado declarado (reporte anterior a la Adenda): prudencia
    assert ri3.tratamiento_fuente({}) == ri3.TRAT_HIPOTESIS


def test_estado_completo_requiere_tres_fuentes_suficientes():
    est, lim = ri3.decidir_estado_procesamiento(ri3.TRAT_USAR, ri3.TRAT_USAR, True)
    assert est == ri3.EST_COMPLETO and lim == []


def test_matriz_fuera_de_alcance_no_es_vacio_ni_degrada(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "false")
    est, lim = ri3.decidir_estado_procesamiento(ri3.TRAT_USAR, ri3.TRAT_USAR, False)
    assert est == ri3.EST_COMPLETO and lim == []


def test_sin_matriz_en_alcance_es_con_limitaciones_y_lo_declara(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    est, lim = ri3.decidir_estado_procesamiento(ri3.TRAT_USAR, ri3.TRAT_USAR, False)
    assert est == ri3.EST_LIMITACIONES
    assert any("Matriz" in x for x in lim)




def test_cp26_ri2_bajo_umbral_declara_limitacion_y_hipotesis():
    est, lim = ri3.decidir_estado_procesamiento(ri3.TRAT_USAR, ri3.TRAT_HIPOTESIS, True)
    assert est == ri3.EST_LIMITACIONES
    assert any("hipótesis" in x for x in lim)


def test_ri3_04_confidencial_se_excluye_y_se_declara():
    est, lim = ri3.decidir_estado_procesamiento(ri3.TRAT_USAR, ri3.TRAT_EXCLUIR, True)
    assert est == ri3.EST_LIMITACIONES
    assert any("no incorpora sus resultados" in x for x in lim)
    assert ri3.extraer_insumos("ri2", {"sintesis_institucional": "x"}, ri3.TRAT_EXCLUIR) is None


def test_sin_reportes_utilizables_no_habilitado():
    est, _ = ri3.decidir_estado_procesamiento(ri3.TRAT_AUSENTE, ri3.TRAT_EXCLUIR, True)
    assert est == ri3.EST_NO_HABILITADO


def test_extraer_insumos_solo_campos_permitidos():
    rep = {"sintesis_institucional": "texto", "n_docentes_activos": 60, "userid": 99}
    texto = ri3.extraer_insumos("ri1", rep, ri3.TRAT_USAR)
    assert "texto" in texto and "60" not in texto and "99" not in texto


# --- Validación del lenguaje ----------------------------------------------

def _salida_valida():
    return {
        "trayectoria": {"situacion_inicial": "Se partió de una necesidad priorizada.",
                        "cambios_observados": "Se observan avances parciales.",
                        "interpretacion": "La institución analizó su proceso."},
        "fortalezas": [{"fortaleza": "Uso de evidencias", "explicacion": "Se observa junto con decisiones posteriores.",
                        "fuentes": ["RI2", "Matriz de análisis institucional"]}],
        "aprendizajes": [{"aprendizaje": "Importancia del seguimiento", "relacion": "Formulado en la Matriz."}],
        "oportunidades": [{"oportunidad": "La profundización del aspecto X", "sustento": "Persiste en RI2.", "sentido": "Continuidad."}],
        "continuidad": {"proyeccion": "p", "coherencia": "c", "condiciones": "k"},
        "tensiones": [],
        "particularidades_por_nivel": [],
        "cierre": {"mensaje_integrado": "La trayectoria permite reconocer avances."},
    }


def test_salida_valida_pasa():
    assert ri3.validar_salida(_salida_valida(), "", False) == []


@pytest.mark.parametrize("frase", [
    "Esto ocurrió gracias a la capacitación.",
    "La mejora ha concluido.",
    "Se recomienda reformular la matriz.",
    "Los docentes deben entregar una nueva versión.",
    "Hay deficiencias en la práctica.",
    "Estado COB_BAJO_UMBRAL del reporte.",
    "El valor es 87 por ciento.",
])
def test_frases_prohibidas_se_detectan(frase):
    s = _salida_valida()
    s["cierre"]["mensaje_integrado"] = frase
    assert ri3.validar_salida(s, "", False)


def test_generalizacion_solo_se_penaliza_con_hipotesis():
    s = _salida_valida()
    s["trayectoria"]["cambios_observados"] = "La mayoría avanzó."
    assert ri3.validar_salida(s, "", False) == []
    assert ri3.validar_salida(s, "", True)


def test_cifra_presente_en_insumos_es_aceptada():
    s = _salida_valida()
    s["cierre"]["mensaje_integrado"] = "Se observó una mejora de 12 puntos."
    assert ri3.validar_salida(s, "avance de 12 puntos", False) == []
    assert ri3.validar_salida(s, "sin cifras", False)


def test_normalizar_sin_matriz_vacia_aprendizajes_y_continuidad():
    out = ri3.normalizar_salida(_salida_valida(), hay_matriz=False)
    assert out["aprendizajes"] == []
    assert out["continuidad"] == {"proyeccion": "", "coherencia": "", "condiciones": ""}


def test_normalizar_topes_y_niveles_invalidos():
    s = _salida_valida()
    s["fortalezas"] = s["fortalezas"] * 5
    s["particularidades_por_nivel"] = [
        {"nivel_educativo": "Superior", "tipo": "cambio", "hallazgo": "x", "evidencia_trazable": []},
        {"nivel_educativo": "Primaria", "tipo": "raro", "hallazgo": "y", "evidencia_trazable": ["RI2"]},
    ]
    out = ri3.normalizar_salida(s, hay_matriz=True)
    assert len(out["fortalezas"]) == 3
    assert [p["nivel_educativo"] for p in out["particularidades_por_nivel"]] == ["Primaria"]
    assert out["particularidades_por_nivel"][0]["tipo"] == "cambio"


# --- Prompt ---------------------------------------------------------------

def test_prompt_marca_hipotesis_y_matriz_ausente():
    trat = {"ri1": ri3.TRAT_USAR, "ri2": ri3.TRAT_HIPOTESIS}
    p = ri3.construir_prompt("IE X", {"ri1": "{}", "ri2": "{}", "matriz": None}, trat, False, en_alcance=True)
    assert "HIPÓTESIS" in p and "NO DISPONIBLE" in p and "la mayoría" in p


def test_prompt_ri2_excluido_no_filtra_contenido():
    trat = {"ri1": ri3.TRAT_USAR, "ri2": ri3.TRAT_EXCLUIR}
    p = ri3.construir_prompt("IE X", {"ri1": '{"a":1}', "ri2": None, "matriz": None}, trat, False)
    assert "NO DISPONIBLE: no la uses" in p


# --- Generación completa con LLM simulado ---------------------------------

def _fuentes(cob1="COB_SUFICIENTE", cob2="COB_SUFICIENTE", matriz=None):
    return {"ri1": _fila(1, cob1), "ri2": _fila(2, cob2), "matriz": matriz}


def _simular_llm(monkeypatch, respuestas):
    cola = list(respuestas)
    llamadas = []

    async def falso(prompt, *, formato_json=False):
        llamadas.append(prompt)
        r = cola.pop(0)
        return r if isinstance(r, str) else json.dumps(r)

    monkeypatch.setattr(ri3, "generar_texto_narrativo", falso)
    return llamadas


def test_generacion_solo_ri1_ri2_con_matriz_desactivada(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "false")
    llamadas = _simular_llm(monkeypatch, [_salida_valida()])
    r = asyncio.run(ri3.generar_reporte_ri3(IE, _fuentes()))
    assert r["estado_procesamiento"] == ri3.EST_COMPLETO
    assert r["fuentes_integradas"] == "RI1 + RI2" and r["matriz_en_alcance"] is False
    assert r["limitaciones"] == [] and r["aprendizajes"] == []
    assert r["continuidad"] == {"proyeccion": "", "coherencia": "", "condiciones": ""}
    # el prompt no menciona la Matriz ni pide aprendizajes
    assert "Matriz" not in llamadas[0] and "únicamente el RI1 y el RI2" in llamadas[0]


def test_generacion_con_limitaciones_matriz_en_alcance_sin_contenido(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    _simular_llm(monkeypatch, [_salida_valida()])
    r = asyncio.run(ri3.generar_reporte_ri3(IE, _fuentes()))
    assert r["estado_procesamiento"] == ri3.EST_LIMITACIONES
    assert r["identificacion_individual_incluida"] is False
    assert r["aprendizajes"] == []                    # sin Matriz no se inventan
    assert r["matriz_disponible"] is False
    assert r["fuentes_utilizadas"] == {"ri1_id": 1, "ri2_id": 2, "matriz_id": None}
    assert [f["fuente"] for f in r["cobertura_fuentes"]] == ["Reporte Institucional 1", "Reporte Institucional 2"]


def test_generacion_completa_con_matriz(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    _simular_llm(monkeypatch, [_salida_valida()])
    r = asyncio.run(ri3.generar_reporte_ri3(IE, _fuentes(matriz={"id": "m1", "texto": "contenido de la matriz"})))
    assert r["estado_procesamiento"] == ri3.EST_COMPLETO
    assert len(r["aprendizajes"]) == 1 and r["advertencia_hipotesis"] is False


def test_reintento_cuando_la_validacion_falla(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    malo = _salida_valida()
    malo["cierre"]["mensaje_integrado"] = "La mejora ha concluido."
    llamadas = _simular_llm(monkeypatch, [malo, _salida_valida()])
    r = asyncio.run(ri3.generar_reporte_ri3(IE, _fuentes(matriz={"id": "m", "texto": "t"})))
    assert len(llamadas) == 2 and "incumplió" in llamadas[1]
    assert r["cierre"]["mensaje_integrado"] == "avances"


def test_fallback_tras_dos_salidas_invalidas(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    malo = _salida_valida()
    malo["cierre"]["mensaje_integrado"] = "La mejora ha concluido."
    _simular_llm(monkeypatch, [malo, "no es json"])
    r = asyncio.run(ri3.generar_reporte_ri3(IE, _fuentes(matriz={"id": "m", "texto": "t"})))
    assert "no fue posible" in r["trayectoria"]["interpretacion"]
    assert r["fortalezas"] == [] and r["identificacion_individual_incluida"] is False


def test_no_habilitado_no_llama_al_llm(monkeypatch):
    llamadas = _simular_llm(monkeypatch, [])
    r = asyncio.run(ri3.generar_reporte_ri3(IE, {"ri1": None, "ri2": _fila(2, "COB_CONFIDENCIAL"), "matriz": None}))
    assert r["estado_procesamiento"] == ri3.EST_NO_HABILITADO
    assert llamadas == [] and "texto_no_habilitado" in r and "fortalezas" not in r


def test_cp27_ri1_nunca_solicitado_se_declara(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    _simular_llm(monkeypatch, [_salida_valida()])
    r = asyncio.run(ri3.generar_reporte_ri3(IE, {"ri1": None, "ri2": _fila(2, "COB_SUFICIENTE"), "matriz": {"id": "m", "texto": "t"}}))
    assert r["estado_procesamiento"] == ri3.EST_LIMITACIONES
    assert any("Reporte Institucional 1" in x for x in r["limitaciones"])


# --- Vigencia y versionado -------------------------------------------------

def test_vigencia_depende_de_las_versiones_de_las_fuentes():
    f = _fuentes()
    firma = ri3.firma_fuentes(f["ri1"], f["ri2"], None)
    guardado = {"id": 7, "reporte_json": {"version_calculo": ri3.VERSION_CALCULO_RI3, "fuentes_firma": firma}}
    assert ri3.ri3_vigente(guardado, firma)
    f2 = copy.deepcopy(f)
    f2["ri2"]["fecha_actualizacion"] = datetime(2026, 11, 9, tzinfo=timezone.utc)
    assert not ri3.ri3_vigente(guardado, ri3.firma_fuentes(f2["ri1"], f2["ri2"], None))
    assert not ri3.ri3_vigente(None, firma)




def test_resumen_fuente_sin_codigos_internos():
    res = ri3.resumen_fuente("ri2", _fila(2, "COB_BAJO_UMBRAL"))
    assert "COB_" not in json.dumps(res, ensure_ascii=False)
    assert ri3.resumen_fuente("ri1", None)["disponible"] is False


# --- Matriz desde Moodle (integración) ---------------------------------------

def _sin_db(monkeypatch):
    async def ultima(clave, tipo):
        return _fila(1 if tipo == "RI1" else 2, "COB_SUFICIENTE")
    monkeypatch.setattr(ri3, "_ultima_fila", ultima)
    monkeypatch.setattr(ri3, "_fila_de_ie", lambda ie, tipo, _f=ultima: _f(ie["clave_ie"], tipo))


def test_matriz_ausente_se_declara_y_no_es_error(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    _sin_db(monkeypatch)

    async def ausente(userid, programa="EBR", descargar=True):
        raise ri3.moodle_matriz.MatrizAusenteError("no la subió")
    monkeypatch.setattr(ri3.moodle_matriz, "obtener_matriz_directivo", ausente)
    f = asyncio.run(ri3._cargar_fuentes(IE, 5, descargar=True))
    assert f["matriz"] is None
    est, lim = ri3.decidir_estado_procesamiento(ri3.TRAT_USAR, ri3.TRAT_USAR, False)
    assert est == ri3.EST_LIMITACIONES and any("Matriz" in x for x in lim)


def test_error_tecnico_de_moodle_no_genera_reporte_degradado(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    _sin_db(monkeypatch)

    async def caido(userid, programa="EBR", descargar=True):
        raise ri3.moodle_matriz.MatrizNoDisponibleError("sin conexión")
    monkeypatch.setattr(ri3.moodle_matriz, "obtener_matriz_directivo", caido)
    with pytest.raises(ri3.moodle_matriz.MatrizNoDisponibleError):
        asyncio.run(ri3._cargar_fuentes(IE, 5, descargar=True))
    # en la consulta rápida no rompe: queda sin verificar
    assert asyncio.run(ri3._cargar_fuentes(IE, 5, descargar=False))["matriz"] is None


def test_consulta_solo_localiza_y_generar_descarga(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    _sin_db(monkeypatch)
    pedidos = []

    async def ok(userid, programa="EBR", descargar=True):
        pedidos.append(descargar)
        return {"id": "c:5:100", "texto": "texto de la matriz" if descargar else None}
    monkeypatch.setattr(ri3.moodle_matriz, "obtener_matriz_directivo", ok)
    asyncio.run(ri3._cargar_fuentes(IE, 5, descargar=False))
    asyncio.run(ri3._cargar_fuentes(IE, 5, descargar=True))
    assert pedidos == [False, True]


def test_matriz_fuera_de_alcance_no_consulta_moodle(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "false")
    _sin_db(monkeypatch)

    async def no_debe_llamarse(*a, **k):
        raise AssertionError("no debe consultar Moodle")
    monkeypatch.setattr(ri3.moodle_matriz, "obtener_matriz_directivo", no_debe_llamarse)
    assert asyncio.run(ri3._cargar_fuentes(IE, 5, descargar=True))["matriz"] is None


def test_nueva_entrega_de_la_matriz_invalida_el_ri3_guardado():
    f = _fuentes()
    firma_vieja = ri3.firma_fuentes(f["ri1"], f["ri2"], {"id": "c:5:100"})
    guardado = {"id": 7, "reporte_json": {"version_calculo": ri3.VERSION_CALCULO_RI3, "fuentes_firma": firma_vieja}}
    assert ri3.ri3_vigente(guardado, firma_vieja)
    assert not ri3.ri3_vigente(guardado, ri3.firma_fuentes(f["ri1"], f["ri2"], {"id": "c:5:200"}))


# --- JEC ---------------------------------------------------------------------

def test_perfiles_por_programa():
    assert ri3.perfil_de(IE)["tipo_ri2"] == "RI2" and ri3.perfil_de(IE)["tipo_ri3"] == "RI3"
    pj = ri3.perfil_de(IE_JEC)
    assert (pj["tipo_ri1"], pj["tipo_ri2"], pj["tipo_ri3"], pj["periodo"]) == ("RI1", "RI2_JEC", "RI3_JEC", "JEC 2026")
    assert ri3.perfil_de({"programa": " jec "})["tipo_ri3"] == "RI3_JEC"
    for malo in (None, "", "OTRO"):
        with pytest.raises(ri3.ProgramaNoSoportadoError):
            ri3.perfil_de({"programa": malo})




def test_reporte_jec_lleva_tipo_y_periodo(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "false")
    _simular_llm(monkeypatch, [_salida_valida()])
    r = asyncio.run(ri3.generar_reporte_ri3(IE_JEC, _fuentes()))
    assert (r["tipo_reporte"], r["periodo"], r["programa"]) == ("RI3_JEC", "JEC 2026", "JEC")
    assert r["identificacion_individual_incluida"] is False


def test_jec_pide_su_matriz_a_moodle(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    _sin_db(monkeypatch)
    vistos = []

    async def ok(userid, programa="EBR", descargar=True):
        vistos.append(programa)
        return {"id": "x", "texto": "t"}
    monkeypatch.setattr(ri3.moodle_matriz, "obtener_matriz_directivo", ok)
    asyncio.run(ri3._cargar_fuentes(IE_JEC, 5, descargar=True))
    asyncio.run(ri3._cargar_fuentes(IE, 5, descargar=True))
    assert vistos == ["JEC", "EBR"]


# --- Pantalla previa: qué insumos hay y qué falta -------------------------------

def _t(r1, r2):
    return {"ri1": r1, "ri2": r2}


def test_todos_los_insumos_disponibles():
    e = ri3.estado_insumos(_t(ri3.TRAT_USAR, ri3.TRAT_USAR), True, en_alcance=True)
    assert e["faltantes"] == [] and e["puede_generar"] is True
    assert "todos los insumos" in e["mensaje"]
    assert [i["fuente"] for i in e["insumos"]] == ["Reporte Institucional 1", "Reporte Institucional 2",
                                                  "Matriz de análisis institucional"]


def test_falta_un_insumo_se_puede_completar_o_generar_parcial():
    e = ri3.estado_insumos(_t(ri3.TRAT_USAR, ri3.TRAT_AUSENTE), True, en_alcance=True)
    assert e["faltantes"] == ["Reporte Institucional 2"] and e["puede_generar"] is True
    assert "Solicite el Reporte Institucional 2" in e["insumos"][1]["accion"]
    assert "completar primero" in e["mensaje"] and "generar el reporte ahora" in e["mensaje"]


def test_falta_la_matriz_se_indica_que_la_suba():
    e = ri3.estado_insumos(_t(ri3.TRAT_USAR, ri3.TRAT_USAR), False, en_alcance=True)
    assert e["faltantes"] == ["Matriz de análisis institucional"] and e["puede_generar"] is True
    assert "Suba su Matriz" in e["insumos"][2]["accion"]


def test_sin_ri1_ni_ri2_no_se_puede_generar():
    e = ri3.estado_insumos(_t(ri3.TRAT_AUSENTE, ri3.TRAT_EXCLUIR), True, en_alcance=True)
    assert e["puede_generar"] is False and "Aún no es posible" in e["mensaje"]
    # coherente con el estado de procesamiento
    assert ri3.decidir_estado_procesamiento(ri3.TRAT_AUSENTE, ri3.TRAT_EXCLUIR, True, True)[0] == ri3.EST_NO_HABILITADO


def test_matriz_fuera_de_alcance_no_aparece_en_la_pantalla():
    e = ri3.estado_insumos(_t(ri3.TRAT_USAR, ri3.TRAT_USAR), False, en_alcance=False)
    assert len(e["insumos"]) == 2 and e["faltantes"] == []


def test_insumo_con_cobertura_baja_esta_disponible_como_hipotesis():
    e = ri3.estado_insumos(_t(ri3.TRAT_HIPOTESIS, ri3.TRAT_USAR), True, en_alcance=True)
    assert e["insumos"][0]["disponible"] and "hipótesis" in e["insumos"][0]["estado"]


def test_pantalla_previa_sin_codigos_internos():
    e = ri3.estado_insumos(_t(ri3.TRAT_EXCLUIR, ri3.TRAT_AUSENTE), False, en_alcance=True)
    assert not re.search(r"COB_|procesamiento_|_[a-z]+_", json.dumps(e, ensure_ascii=False))


# --- Nunca se generan RI1 ni RI2 desde aquí ----------------------------------------

def test_no_existe_generacion_de_fuentes():
    assert not hasattr(ri3, "_generar_ri2_para_ri3")


def test_fuentes_faltantes_no_se_generan_en_ninguno_de_los_programas(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "false")
    pedidos = []

    async def ultima(clave, tipo):
        pedidos.append(tipo)
        return None
    monkeypatch.setattr(ri3, "_ultima_fila", ultima)
    monkeypatch.setattr(ri3, "_fila_de_ie", lambda ie, tipo, _f=ultima: _f(ie["clave_ie"], tipo))
    for ie in (IE, IE_JEC):
        f = asyncio.run(ri3._cargar_fuentes(ie, 5, descargar=True))
        assert f == {"ri1": None, "ri2": None, "matriz": None}
    # Solo se leen RI1/RI2 (nunca se generan); cada tipo puede probarse con
    # más de una clave de la misma IE.
    assert list(dict.fromkeys(pedidos)) == ["RI1", "RI2", "RI2_JEC"]
    assert set(pedidos) == {"RI1", "RI2", "RI2_JEC"}


def test_claves_candidatas_cubren_las_epocas_de_guardado():
    """Un RI1 guardado con la clave compuesta (con o sin UGEL) se encuentra
    aunque la IE tenga hoy cod_institucional."""
    ie = {**IE, "clave_ie": "1", "nombre_ie": "IE X", "ugel": "U", "region": "R", "distrito": "D"}
    claves, patron = ri3._claves_ie(ie)
    assert claves == ["1", "IE X|U|R|D", "IE X|R|D"]
    assert patron == "IE X|%|R|D"


def test_claves_candidatas_sin_cod_institucional_no_se_duplican():
    ie = {**IE, "clave_ie": "IE X|U|R|D", "nombre_ie": "IE X", "ugel": "U", "region": "R", "distrito": "D"}
    assert ri3._claves_ie(ie)[0] == ["IE X|U|R|D", "IE X|R|D"]


def test_patron_escapa_comodines_del_nombre():
    ie = {**IE, "clave_ie": "k", "nombre_ie": "IE 50%_A", "ugel": "U", "region": "R", "distrito": "D"}
    assert ri3._claves_ie(ie)[1] == r"IE 50\%\_A|%|R|D"


def test_reporte_json_como_texto_se_acepta_y_el_vacio_se_descarta():
    assert ri3._reporte_dict({"reporte_json": '{"a": 1}'})["reporte_json"] == {"a": 1}
    assert ri3._reporte_dict({"reporte_json": "no es json"}) is None
    assert ri3._reporte_dict({"reporte_json": {}}) is None
    assert ri3._reporte_dict(None) is None


def test_sin_fuentes_el_reporte_no_se_genera_ni_se_guarda(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "false")

    async def resolver(userid):
        return IE

    async def sin_fila(clave, tipo):
        return None

    async def no_guardar(*a, **k):
        raise AssertionError("no debe guardar")
    monkeypatch.setattr(ri3, "_resolver_ie_ri3", resolver)
    monkeypatch.setattr(ri3, "_ultima_fila", sin_fila)
    monkeypatch.setattr(ri3, "_fila_de_ie", lambda ie, tipo, _f=sin_fila: _f(ie["clave_ie"], tipo))
    monkeypatch.setattr(ri3, "_guardar_ri3", no_guardar)
    monkeypatch.setattr(ri3, "_registrar_consulta_ri3", no_guardar)
    llamadas = _simular_llm(monkeypatch, [])
    r = asyncio.run(ri3.obtener_o_generar_ri3(5, 1, 1))
    assert r["estado_procesamiento"] == ri3.EST_NO_HABILITADO and llamadas == []
    assert "version_reporte" not in r and "origen_version" not in r


def test_consultar_devuelve_la_pantalla_previa(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "false")

    async def resolver(userid):
        return IE

    async def ultima(clave, tipo):
        return _fila(1, "COB_SUFICIENTE") if tipo == "RI1" else None
    monkeypatch.setattr(ri3, "_resolver_ie_ri3", resolver)
    monkeypatch.setattr(ri3, "_ultima_fila", ultima)
    monkeypatch.setattr(ri3, "_fila_de_ie", lambda ie, tipo, _f=ultima: _f(ie["clave_ie"], tipo))
    d = asyncio.run(ri3.consultar_ri3(5))
    assert d["accion"] == "generar" and d["puede_generar"] is True
    assert d["faltantes"] == ["Reporte Institucional 2"] and "mensaje" in d
    assert "version" not in json.dumps(d["cobertura_fuentes"])


def test_oportunidad_que_empieza_con_verbo_se_rechaza():
    data = _salida_valida()
    data["oportunidades"][0]["oportunidad"] = "Fortalecer el acompañamiento entre pares"
    data["oportunidades"][0]["sentido"] = "Promover el análisis de casos."
    problemas = ri3.validar_salida(data, "", False)
    assert sum("prescriptiva" in p for p in problemas) == 2


def test_oportunidad_nominal_es_valida():
    data = _salida_valida()
    data["oportunidades"][0]["oportunidad"] = "El acompañamiento entre pares como ámbito de continuidad"
    assert not [p for p in ri3.validar_salida(data, "", False) if "prescriptiva" in p]


def test_mensaje_de_cierre_completa_la_frase_del_modelo():
    data = _salida_valida()
    data["cierre"]["mensaje_integrado"] = "Un compromiso sostenido con la mejora."
    assert ri3.normalizar_salida(data, True)["cierre"]["mensaje_integrado"] == "un compromiso sostenido con la mejora"


def test_reporte_trae_el_marco_fijo_del_cierre():
    r = ri3.armar_reporte(IE, ri3.EST_COMPLETO, [], [], {"ri1": "usar", "ri2": "usar"}, True,
                          ri3.narrativa_fallback([]), {}, {})
    assert r["cierre_apertura"] == "La trayectoria institucional desarrollada durante el Programa EBR 2026 permite reconocer"
    assert r["cierre_continuidad"].startswith("Los avances identificados")


def test_si_solo_hay_estilo_prescriptivo_se_retira_y_no_se_degrada(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    malo = _salida_valida()
    malo["oportunidades"] = [
        {"oportunidad": "Fortalecer la retroalimentación", "sustento": "s", "sentido": "x"},
        {"oportunidad": "La retroalimentación escrita", "sustento": "Persiste en RI2.", "sentido": "Promover el análisis."},
    ]
    _simular_llm(monkeypatch, [malo, malo])
    r = asyncio.run(ri3.generar_reporte_ri3(IE, _fuentes(matriz={"id": "m", "texto": "t"})))
    assert [o["oportunidad"] for o in r["oportunidades"]] == ["La retroalimentación escrita"]
    assert r["oportunidades"][0]["sentido"] == ""
    assert r["fortalezas"]            # el resto del reporte se conserva


def test_un_reporte_degradado_no_queda_vigente():
    firma = {"ri1": 1}
    ok = {"reporte_json": {"version_calculo": ri3.VERSION_CALCULO_RI3, "fuentes_firma": firma}}
    assert ri3.ri3_vigente(ok, firma) is True
    ok["reporte_json"]["narrativa_degradada"] = True
    assert ri3.ri3_vigente(ok, firma) is False


def test_la_matriz_transcrita_se_guarda_por_version_del_archivo(monkeypatch):
    import moodle_matriz as mm
    mm._TEXTOS.clear(); mm._EN_CURSO.clear()
    llamadas = []

    async def entrega(userid, programa="EBR", client=None):
        return {"id": "9:1:100", "filename": "m.pdf", "fileurl": "u"}

    async def extraer(e, client=None):
        llamadas.append(e["id"])
        return "texto"
    monkeypatch.setattr(mm, "localizar_entrega", entrega)
    monkeypatch.setattr(mm, "descargar_y_extraer", extraer)

    async def flujo():
        a = await mm.obtener_matriz_directivo(1, descargar=True)
        b = await mm.obtener_matriz_directivo(1, descargar=True)
        return a, b
    a, b = asyncio.run(flujo())
    assert a["texto"] == b["texto"] == "texto" and llamadas == ["9:1:100"]


def test_la_matriz_guardada_se_reutiliza_sin_volver_a_leerla(monkeypatch):
    import moodle_matriz as mm
    guardados, extracciones = {}, []

    async def leer(e):
        return guardados.get(e["id"])

    async def guardar(e, t):
        guardados[e["id"]] = t

    async def extraer(e, client=None):
        extracciones.append(e["id"])
        return "texto leído"
    mm.configurar_almacen(leer, guardar)
    monkeypatch.setattr(mm, "descargar_y_extraer", extraer)
    e = {"id": "9:1:100", "filename": "m.pdf", "fileurl": "u"}
    assert asyncio.run(mm._texto_de(e)) == "texto leído"
    mm._TEXTOS.clear()                        # simula un reinicio del servicio
    assert asyncio.run(mm._texto_de(e)) == "texto leído"
    assert extracciones == ["9:1:100"] and guardados == {"9:1:100": "texto leído"}
    otra = {**e, "id": "9:1:200"}             # el directivo volvió a subir el archivo
    asyncio.run(mm._texto_de(otra))
    assert extracciones == ["9:1:100", "9:1:200"]


def test_si_el_almacen_falla_se_sigue_sin_el(monkeypatch):
    import moodle_matriz as mm

    async def roto(*a):
        raise RuntimeError("sin base")

    async def extraer(e, client=None):
        return "texto"
    mm.configurar_almacen(roto, roto)
    monkeypatch.setattr(mm, "descargar_y_extraer", extraer)
    assert asyncio.run(mm._texto_de({"id": "9:1:1", "filename": "m.pdf", "fileurl": "u"})) == "texto"


def test_mensaje_de_cierre_no_repite_el_marco_fijo():
    data = _salida_valida()
    data["cierre"]["mensaje_integrado"] = ("La trayectoria institucional desarrollada durante el Programa permite reconocer "
                                           "la continuidad en la alineación de los propósitos.")
    assert ri3.normalizar_salida(data, True)["cierre"]["mensaje_integrado"] == "la continuidad en la alineación de los propósitos"


def test_valoracion_sin_respaldo_en_los_insumos_se_detecta():
    data = _salida_valida()
    data["fortalezas"][0]["explicacion"] = "Es fundamental para la relevancia de la enseñanza."
    assert any("valoración" in p for p in ri3.validar_salida(data, "", False))
    assert not any("valoración" in p for p in ri3.validar_salida(data, "algo fundamental en los insumos", False))


def test_proyeccion_como_orden_se_rechaza_y_atribuida_a_la_institucion_no():
    data = _salida_valida()
    data["continuidad"]["proyeccion"] = "Lograr que más docentes mejoren."
    assert any("prescriptiva" in p for p in ri3.validar_salida(data, "", False))
    data["continuidad"]["proyeccion"] = "La institución proyecta lograr que más docentes mejoren."
    assert not any("prescriptiva" in p for p in ri3.validar_salida(data, "", False))


def test_el_codigo_numerico_del_nombre_de_la_ie_no_cuenta_como_cifra_inventada(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    ie = {**IE, "nombre_ie": "14011 NUESTRA SEÑORA DEL PILAR"}
    data = _salida_valida()
    data["trayectoria"]["situacion_inicial"] = "La institución 14011 NUESTRA SEÑORA DEL PILAR partió de una necesidad priorizada."
    llamadas = _simular_llm(monkeypatch, [data])
    r = asyncio.run(ri3.generar_reporte_ri3(ie, _fuentes(matriz={"id": "m", "texto": "t"})))
    assert len(llamadas) == 1 and not r.get("narrativa_degradada")


def test_si_moodle_no_responde_al_consultar_se_muestra_el_ri3_guardado(monkeypatch):
    monkeypatch.setenv("USAR_MATRIZ", "true")
    import moodle_matriz as mm
    from datetime import datetime
    f1 = {"id": 1, "cod_modular": "k", "estado": "generado", "n_docentes_evaluados": 0, "reporte_json": {"estado_cobertura": "COB_SUFICIENTE"},
          "fecha_generacion": datetime(2026, 1, 1), "fecha_actualizacion": datetime(2026, 1, 1)}
    f2 = {**f1, "id": 2}
    firma = ri3.firma_fuentes(f1, f2, {"id": "9:1:100"})
    guardado = {"id": 7, "reporte_json": {"version_calculo": ri3.VERSION_CALCULO_RI3, "fuentes_firma": firma, "nombre_ie": "IE"}}

    async def resolver(userid):
        return IE

    async def fila(ie, tipo):
        return f1 if tipo == "RI1" else f2

    async def sin_moodle(*a, **k):
        raise mm.MatrizNoDisponibleError("caído")

    async def leer_guardado(ie, userid):
        return guardado
    monkeypatch.setattr(ri3, "_resolver_ie_ri3", resolver)
    monkeypatch.setattr(ri3, "_fila_de_ie", fila)
    monkeypatch.setattr(ri3, "obtener_matriz", sin_moodle)
    monkeypatch.setattr(ri3, "obtener_ri3_guardado", leer_guardado)
    r = asyncio.run(ri3.consultar_ri3(5))
    assert r["accion"] == "mostrar" and r["reporte"] is guardado["reporte_json"]


def test_el_ri3_se_guarda_por_directivo_y_no_por_ie():
    ie = {**IE, "clave_ie": "IE-9"}
    assert ri3.clave_ri3(ie, 111) == "IE-9#111"
    assert ri3.clave_ri3(ie, 222) == "IE-9#222"          # otro directivo de la misma IE: otro reporte


def test_dos_directivos_de_la_misma_ie_no_se_pisan(monkeypatch):
    """Cada directivo tiene su Matriz: lo guardado se busca y se escribe con su propia clave."""
    monkeypatch.setenv("USAR_MATRIZ", "true")
    leidas, escritas = [], []

    async def ultima(clave, tipo):
        leidas.append(clave)
        return None

    async def guardar(clave, reporte, tipo):
        escritas.append(clave)
        return 1

    async def nada(*a, **k):
        return None

    async def resolver(userid):
        return {**IE, "userid": userid}

    async def fuentes(ie, userid, descargar):
        return _fuentes(matriz={"id": f"1:{userid}:5", "texto": f"matriz de {userid}"})

    async def generar(ie, f):
        return {"estado_procesamiento": "procesamiento_completo", "userid_directivo": ie["userid"]}
    monkeypatch.setattr(ri3, "_ultima_fila", ultima)
    monkeypatch.setattr(ri3, "_guardar_ri3", guardar)
    monkeypatch.setattr(ri3, "_registrar_consulta_ri3", nada)
    monkeypatch.setattr(ri3, "_resolver_ie_ri3", resolver)
    monkeypatch.setattr(ri3, "_cargar_fuentes", fuentes)
    monkeypatch.setattr(ri3, "generar_reporte_ri3", generar)
    for uid in (111, 222):
        asyncio.run(ri3.obtener_o_generar_ri3(uid, 1, 1))
    assert escritas == [f"{IE['clave_ie']}#111", f"{IE['clave_ie']}#222"]
    assert set(leidas) == set(escritas)


def test_el_reporte_registra_el_directivo():
    r = ri3.armar_reporte({**IE, "userid": 294883}, ri3.EST_COMPLETO, [], [], {"ri1": "usar", "ri2": "usar"}, True,
                          ri3.narrativa_fallback([]), {}, {})
    assert r["userid_directivo"] == 294883 and "294883" in r["reporte_id"]


def test_matriz_en_alcance_por_defecto(monkeypatch):
    monkeypatch.delenv("USAR_MATRIZ", raising=False)
    assert ri3.matriz_en_alcance() is True
