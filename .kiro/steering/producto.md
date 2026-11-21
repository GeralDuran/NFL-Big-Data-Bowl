# Producto: PocketSync — Reloj de Presión y Sincronía (Hackathon NFL Big Data Bowl, UNAM)

Este archivo describe la idea del equipo. Las reglas técnicas del evento están en `rules.md` y tienen prioridad.

- **El dataset está FUERA del proyecto**, en la carpeta hermana `../data` (relativa a la raíz del proyecto). En la compu de Samuel es `C:\Users\sami2\Documents\Hackaton\NFL\plantilla-hackathon\data`.
  - Contiene `games.csv`, `plays.csv`, `players.csv`, `pffScoutingData.csv` y `tracking/tracking_<gameId>.csv`.
  - La ruta se define en una sola constante: variable de entorno `NFL_DATA_DIR` y, si no existe, `<raíz del proyecto>/../data`, usando `pathlib`. Nunca la escribas absoluta en el código.
  - Solo `backend/precompute.py` lee esa carpeta. El servidor (`backend/main.py`) NO la lee nunca: solo carga `backend/data_summary.json`.
  - No tienes acceso a esa carpeta ni debes abrirla: confía en las columnas descritas en este archivo.
- No cambies la estructura de carpetas del proyecto.

## Visión

**Usuario objetivo:** coach o coordinador ofensivo de la NFL.

**Problema:** en situaciones críticas de pase (por ejemplo, 3rd & 7), el coach ve el resultado final (completo, incompleto o sack), pero no sabe qué ocurrió primero: ¿colapsó el bolsillo alrededor del QB o se abrió una ventana de separación para los receptores?

**Propuesta:** convertir el tracking cuadro por cuadro (10 Hz) y las evaluaciones de PFF en un **Reloj de Presión y Sincronía**. Con él se ve qué formaciones, el uso de Play Action y qué tipos de bloqueo generan más separación antes de que llegue la presión.

## Métricas propias

Todas se calculan con coordenadas normalizadas (ver "Preprocesamiento").

- **PCT — Pocket Collapse Time (segundos):** desde `ball_snap` (si no existe, `autoevent_ballsnap`) hasta el primer frame en que un defensor con `pff_role == "Pass rush"` entra al radio de **2.0 yardas** del QB (`pff_role == "Pass"`). Solo cuenta a partir de **0.5 s (5 frames)** después del snap y solo si ese pass rusher está **más cerca del QB que en el frame del snap**, para evitar falsas presiones en formaciones bajo centro. El radio de 2.0 yardas se validó contra las etiquetas de PFF (presión PFF = alguna fila de la jugada con `pff_hit`, `pff_hurry` o `pff_sack` = 1): tasa de presión ~34% contra ~36% de PFF y ~83% de coincidencia por jugada. `precompute.py` guarda esa validación en `meta.validacion_pff` y la muestra en consola.
  - Si nunca entra, PCT = tiempo hasta el evento final (lanzamiento, sack o scramble) y la jugada se marca `presion = False`.
- **TTT — Time to Throw (segundos):** desde `ball_snap` hasta `pass_forward` / `autoevent_passforward`.
- **TWS — Target Window Separation (yardas):** se mide en el frame del lanzamiento.
  1. Para cada receptor con `pff_role == "Pass route"`, se calcula la distancia al defensor más cercano con `pff_role == "Coverage"`.
  2. **TWS = la mayor de esas distancias** (la ventana del receptor más abierto).
  - Se guarda también la separación por receptor (`nflId`), para el ranking de receptores.
- **PSI — Pocket-to-Separation Index** = TWS / max(PCT, 1.0).
  - Se usa un piso de 1.0 s para que los lanzamientos ultrarrápidos no inflen el índice.
  - Solo se calcula en jugadas con lanzamiento.

## Limitaciones reales del dataset (respetarlas, no inventar datos)

1. **No existe columna de "receptor objetivo".** Por eso TWS usa al receptor más abierto, no al que recibió el pase.
2. **El tracking termina en el lanzamiento, el sack (`qb_sack`, `qb_strip_sack`) o el scramble (`run`).** No hay trayectoria del balón en el aire.
3. **En los sacks no hay lanzamiento**, así que no hay TWS ni PSI. Se cuentan aparte (tasa de sack, PCT).
4. **Solo hay jugadas de pase.** No se puede recomendar correr contra pasar.
5. Si una jugada no tiene QB identificado, o le falta el snap o el evento final, se descarta y se cuenta en un log de jugadas excluidas.

## Preprocesamiento offline (`backend/precompute.py`)

- Se ejecuta a mano, una sola vez, desde la raíz del proyecto con el Python de `.venv`. El servidor nunca lo ejecuta.
- Lee los archivos de `<NFL_DATA_DIR>/tracking/` uno por uno, con `usecols`, sin cargar todos a la vez. También lee `plays.csv`, `pffScoutingData.csv`, `players.csv` y `games.csv`.
- **Normaliza:** si `playDirection == "left"`, entonces `x = 120 - x`, `y = 53.3 - y`, `o = (o + 180) % 360` y `dir = (dir + 180) % 360`. Así el ataque siempre avanza hacia la derecha.
- **Genera `backend/data_summary.json` (menos de 5 MB)** con:
  - métricas por jugada (gameId, playId, equipo, down, yardsToGo, formación, play action, cobertura, tipo de cobertura, PCT, TTT, TWS, PSI, presión, passResult y playResult),
  - rankings agregados por equipo ofensivo, QB, liniero, defensivo y receptor,
  - matriz situacional: down × distancia (corta 1-3, media 4-7, larga 8+) × formación × play action × tipo de cobertura (Man/Zone), con número de jugadas, PCT, TWS, PSI promedio, tasa de éxito (playResult >= yardsToGo) y tasa de sack,
  - efecto de los bloqueos de ayuda (`pff_blockType` CH y SW contra PP) en el PCT, en 3rd down,
  - trayectorias cuadro por cuadro de **20 jugadas representativas**: sacks rápidos, PSI alto, PSI bajo, Play Action, 3rd & largo, etc.
- Muestra en consola un resumen con los hallazgos clave (los números reales) y un log de jugadas excluidas.
- La carpeta del dataset es de solo lectura: nunca escribas ahí.
- Si la carpeta no existe, muestra un error claro que diga dónde la buscó y cómo definir `NFL_DATA_DIR`.

## API (`backend/main.py`)

- Al arrancar, carga solo `backend/data_summary.json`; no lee tracking. Mantén `GET /health`.
- `GET /api/summary`: rankings, matriz e hipótesis, con filtros opcionales.
- `GET /api/plays`: lista de las 20 jugadas disponibles en el Film Room.
- `GET /api/play/{game_id}/{play_id}`: frames normalizados con los eventos, el frame de PCT, TWS por receptor y el resultado.
- `GET /api/playcaller?down=&yardas=&cobertura=`: recomendación sin IA (formación, Play Action y bloqueo) más el top 3. Si se pide un rival, filtrar por `defensiveTeam`.
- `POST /api/coordinator {pregunta}`: agente Strands + Amazon Nova configurado según `rules.md`. Sus herramientas son las funciones de summary y de playcaller. Responde en español y cita los números.
  - Si Bedrock falla, devuelve un mensaje amable y la app sigue funcionando.

## Dashboard (`dashboard/`)

- **Módulo 1 — Rankings de Trinchera y Separación:**
  - Tablas y gráficas en Recharts: barras por equipo y un scatter de PCT contra TWS.
  - Filtros por down, formación y tipo de cobertura.
  - Tarjetas con las cuatro hipótesis respondidas con datos: efecto del Play Action, bloqueos de ayuda, formaciones bajo presión y talento de linieros y receptores.
- **Módulo 2 — Film Room 2D:**
  - Cancha SVG de 120 × 53.3 yardas con 22 jugadores y el balón animados a 10 fps, con Play/Pausa/Reiniciar y velocidad.
  - Un cronómetro corre desde el snap y se detiene en el evento final.
  - Un anillo de 2.0 yardas alrededor del QB cambia de verde a rojo cuando entra un pass rusher.
  - Líneas de separación entre cada receptor y su defensor más cercano.
  - Al final, una tarjeta con el resultado, las yardas, el PCT, el TWS y el PSI.
- **Módulo 3 — Play-Caller:**
  - Selectores de down, yardas y cobertura que devuelven la recomendación y el top 3.
  - Chat con el AI Coordinator.

## Reglas de trabajo (ahorro de tokens y calidad)

- **Nunca abras ni leas los CSV del dataset**, sobre todo los de `tracking/`. Para conocer un archivo, usa solo los encabezados o las primeras 5 filas.
- Interfaz y código comentados en español, simples: el equipo está aprendiendo.
- No inventes números: todo dato mostrado debe salir de `data_summary.json`.
