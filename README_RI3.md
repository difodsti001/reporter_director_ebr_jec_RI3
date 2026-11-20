# RI3 (EBR y JEC 2026)

Cierre reflexivo de la trayectoria. No evalúa ni recalcula: sintetiza el RI1, el RI2 y la Matriz
de análisis institucional ya producidos.

## Archivos
`ri3.py` (lógica), `moodle_matriz.py` (lee la Matriz de Moodle), `templates/index_ri3.html`,
`tests/test_ri3.py`, `tests/test_moodle_matriz.py`. `app.py` agrega `/reporte_director_ri3`,
`/reporte_ri3/consultar` y `/reporte_ri3/generar`. `core.py` solo conserva lo que usa el RI3 (logging, pools, resolución de la IE); el código del RI2 se retiró porque tiene su propio servicio.

## Cómo funciona
1. **Consulta** (`/reporte_ri3/consultar`, solo lectura, sin LLM): si hay un RI3 vigente lo muestra;
   si no, muestra la **pantalla previa** con los insumos (RI1, RI2, Matriz), cuáles faltan y qué hacer.
2. **Generar** (`/reporte_ri3/generar`): el usuario elige completar los insumos primero o generar el
   RI3 con lo disponible (el reporte lo declara y su lectura es más limitada).
   Sin RI1 ni RI2 utilizables no se genera ni se guarda nada.
3. **RI1 y RI2 nunca se generan aquí**: cada uno tiene su servicio; viven en la misma base
   (`f4_reportes_directivo`). EBR lee `RI1`+`RI2` y guarda `RI3`; JEC lee `RI1`+`RI2_JEC` y guarda `RI3_JEC`.
4. **Sin versiones**: una fila por IE y tipo. El RI3 se regenera solo si cambian sus fuentes.

## Cobertura heredada (Adenda sec. 10)
Cobertura baja en una fuente: lo que derive de ella se redacta como hipótesis. Confidencial: no se
incorpora y se declara. El estado de procesamiento sigue la Ficha (completo / con limitaciones /
no habilitado).

## Matriz (Moodle)
Actividades (`moodle_matriz.MATRICES`): EBR curso 2919 / cmid 213169; JEC curso 2998 / cmid 213268.
PDF (o DOCX como alternativa). Para activarla, en `.env`: `MOODLE_BASE_URL`, `MOODLE_SERVICE_PATH`,
`MOODLE_TOKEN` y `USAR_MATRIZ=true`. Con `USAR_MATRIZ=false` queda fuera (por defecto es `true`): el RI3 integra
RI1 + RI2 y omite aprendizajes y continuidad.
- Sin Matriz utilizable (no la subió, ilegible, > 20 MB): se informa en la pantalla previa y el RI3 lo declara.
- Error técnico de Moodle: no se genera ni se guarda nada (HTTP 503).

## Supuestos pendientes de coordinación
- JEC usa las mismas reglas que EBR (no hay Ficha/Instrumento RI3 de JEC).
- Conflicto Ficha vs. Adenda: se mantienen los 3 estados de la Ficha; la cobertura heredada es un campo aparte.

## Texto de la Matriz guardado

Leer la Matriz con visión tarda; el archivo se sube una sola vez. El texto se guarda en la tabla
`f4_matriz_directivo` (se crea sola la primera vez), una fila por directivo y actividad, identificada
por la versión del archivo en Moodle (`cmid:userid:fecha de modificación`) y la versión del método de
extracción (`EXTRACCION_VERSION` en `moodle_matriz.py`). Si el directivo sube otro archivo, la fila se
reemplaza. Contiene el texto tal como lo escribió el directivo: puede incluir nombres de docentes, por lo
que conviene restringir el acceso a esa tabla. Se precalienta al abrir la pantalla de insumos.

Seguridad: el token de Moodle viaja en la URL de descarga (lo exige `pluginfile.php`); el log del cliente
HTTP lo oculta (`token=***`). `MOODLE_DISABLE_SSL_VERIFY_DEV_ONLY` y `DISABLE_SSL_VERIFY_DEV_ONLY` son solo
para desarrollo.

## El RI3 es individual por directivo

El RI1 y el RI2 son de la IE: los ve cualquiera de sus directivos y se guardan una vez por IE. El RI3, en
cambio, integra la **Matriz individual** de cada directivo, así que se guarda **un reporte por IE y directivo**
en `f4_reportes_directivo`, con `cod_modular = "<clave_ie>#<userid>"` y `tipo_reporte` RI3 / RI3_JEC
(`clave_ri3` en `ri3.py`). El reporte lleva `userid_directivo`. Los dos directivos de una misma IE comparten
el RI1 y el RI2, pero cada uno ve y regenera solo el suyo; no se pisan.
