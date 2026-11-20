# RI3 (EBR y JEC 2026)

Cierre reflexivo de la trayectoria. No evalúa ni recalcula: sintetiza el RI1, el RI2 y la Matriz
de análisis institucional ya producidos.

## Archivos
`ri3.py` (lógica), `moodle_matriz.py` (lee la Matriz de Moodle), `templates/index_ri3.html`,
`tests/test_ri3.py`, `tests/test_moodle_matriz.py`. `app.py` agrega `/reporte_director_ri3`,
`/reporte_ri3/consultar` y `/reporte_ri3/generar`. `core.py` solo conserva lo que usa el RI3 (logging, pools, resolución de la IE); el código del RI2 se retiró porque tiene su propio servicio.

## Cómo funciona
1. **Consulta** (`/reporte_ri3/consultar`, solo lectura, sin LLM): si hay un RI3 vigente lo muestra;
   si no, muestra la **pantalla previa** con el estado de los tres insumos (RI1, RI2, Matriz). No lee
   la Matriz: solo comprueba que exista la entrega.
2. **Insumos obligatorios**: sin RI1, RI2 o Matriz no se genera nada (`procesamiento_no_habilitado`). La
   pantalla indica qué falta y que debe solicitarse/subirse desde el aula virtual (sin enlace).
3. **Generar** (`/reporte_ri3/generar`): se hace a solicitud del directivo. Ahí se descarga y lee la
   Matriz (tarda unos minutos) y se redacta el reporte.
4. **RI1 y RI2 nunca se generan aquí**: cada uno tiene su servicio; viven en la misma base
   (`f4_reportes_directivo`). EBR lee `RI1`+`RI2` y guarda `RI3`; JEC lee `RI1`+`RI2_JEC` y guarda `RI3_JEC`.
5. **Versiones**: una sola fila por directivo; la versión va dentro del JSON (`version`,
   `version_anterior`, `versiones_anteriores`). Solicitar de nuevo con información actualizada crea la
   versión N+1 y conserva la anterior en el mismo registro. A la página llega solo `historial_versiones`.
   Un intento que no pudo redactarse (`narrativa_degradada`) no cuenta como versión.

## Estado y cobertura (Ficha vs. Adenda)
El **estado** depende solo de que estén las fuentes (completo / no habilitado). La **cobertura** baja o
confidencial de RI1/RI2 se declara en el texto y lo que derive de ella se redacta como hipótesis (o se
excluye); no cambia el estado. `con_limitaciones` queda reservado a vacíos internos relevantes: hoy
ninguna regla lo asigna.

## Particularidades por nivel
Se muestran todos los niveles con evidencia suficiente y trazable (favorable o de avance limitado), sin
comparar ni jerarquizar. La Matriz sola basta si no contradice al RI1/RI2. JEC solo tiene Secundaria: no
lleva esta tabla.

## Matriz (Moodle)
Actividades (`moodle_matriz.MATRICES`): EBR curso 2919 / cmid 213169; JEC curso 2998 / cmid 213268.
PDF (o DOCX como alternativa). Para activarla, en `.env`: `MOODLE_BASE_URL`, `MOODLE_SERVICE_PATH`,
`MOODLE_TOKEN` y `USAR_MATRIZ=true`. Con `USAR_MATRIZ=false` queda fuera (por defecto es `true`): el RI3 integra
RI1 + RI2 y omite aprendizajes y continuidad.
- Sin Matriz utilizable (no la subió, ilegible, > 20 MB): se informa en la pantalla previa y el RI3 queda no habilitado.
- Error técnico de Moodle: no se genera ni se guarda nada (HTTP 503).

## Reglas confirmadas por el área pedagógica
- JEC usa la misma configuración que EBR, con un solo nivel (Secundaria). Los perfiles del equipo directivo
  (director/a, subdirector/a, coordinadores) ya están estandarizados como `DIRECTIVO` en la base.
- Ficha vs. Adenda: estado y cobertura se tratan por separado (ver arriba).
- Fuera de este servicio: que el RI3 sea una actividad obligatoria en el aula virtual se configura en Moodle.

## Texto de la Matriz guardado

Leer la Matriz con visión tarda; el archivo se sube una sola vez. El texto se guarda en la tabla
`f4_matriz_directivo` (se crea sola la primera vez), una fila por directivo y actividad, identificada
por la versión del archivo en Moodle (`cmid:userid:fecha de modificación`) y la versión del método de
extracción (`EXTRACCION_VERSION` en `moodle_matriz.py`). Si el directivo sube otro archivo, la fila se
reemplaza. Contiene el texto tal como lo escribió el directivo: puede incluir nombres de docentes, por lo
que conviene restringir el acceso a esa tabla. La pantalla de insumos no la lee: la lectura ocurre al solicitar el reporte.

Seguridad: el token de Moodle viaja en la URL de descarga (lo exige `pluginfile.php`); el log del cliente
HTTP lo oculta (`token=***`). `MOODLE_DISABLE_SSL_VERIFY_DEV_ONLY` y `DISABLE_SSL_VERIFY_DEV_ONLY` son solo
para desarrollo.

## El RI3 es individual por directivo

El RI1 y el RI2 son de la IE: los ve cualquiera de sus directivos y se guardan una vez por IE. El RI3, en
cambio, integra la **Matriz individual** de cada directivo, así que se guarda **un reporte por IE y directivo**
en `f4_reportes_directivo`, con `cod_modular = "<clave_ie>#<userid>"` y `tipo_reporte` RI3 / RI3_JEC
(`clave_ri3` en `ri3.py`). El reporte lleva `userid_directivo`. Los dos directivos de una misma IE comparten
el RI1 y el RI2, pero cada uno ve y regenera solo el suyo; no se pisan.
