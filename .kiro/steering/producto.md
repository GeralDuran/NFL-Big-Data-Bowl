# Producto: qué construimos (Hackathon NFL Big Data Bowl, UNAM)

Este archivo describe la idea del equipo. Las reglas técnicas del evento están en `rules.md` y tienen prioridad. Los datos se leen desde `data/data/` con rutas relativas a la raíz del proyecto; no cambies la estructura de carpetas.

## Idea

Una app para coaches y analistas que responde a una pregunta: **¿qué tan bien protege cada ofensiva a su quarterback y cuánto tiempo tiene el QB antes de la presión?**

Tiene tres módulos:

1. **Ranking de protección**
   - Ranking por equipo ofensivo y por liniero de sacks, hits y hurries permitidos.
   - Ranking de los defensivos que más presión generan.
   - Mostrar qué ofensivas son más débiles y en qué situaciones: por down, distancia, formación y tipo de dropback.
2. **Visualizador de jugadas + reloj de presión**
   - Se elige una jugada y se anima sobre un campo dibujado en SVG.
   - Un reloj corre desde el snap.
   - Cuando la jugada termina (el QB lanza, es capturado o sale corriendo), el reloj se detiene y se muestran:
     - el tiempo en el pocket,
     - el resultado (completo, incompleto, sack, intercepción o scramble),
     - las yardas ganadas,
     - el momento en que hubo presión, si la hubo.
3. **Asistente de situaciones (agente IA)**
   - El usuario indica down y yardas por avanzar (por ejemplo, 3ª y 7) y recibe la mejor opción según los datos: formación, play action o no, tipo de dropback, y la cobertura que más le ha costado a la ofensiva.
   - Debe existir un endpoint sin IA que devuelva la tabla de recomendaciones. El agente (Strands + Amazon Nova) solo la explica en lenguaje natural.
   - Si Bedrock falla, la app sigue funcionando con la tabla.

## Datos (en `data/data/`, estructura del kit: no moverla)

- `games.csv`, clave `gameId`.
- `plays.csv`, claves `gameId` y `playId`. Contiene down, yardsToGo, offenseFormation, dropBackType, pff_playAction, pff_passCoverage, passResult (C, I, S, IN, R) y playResult (yardas).
- `players.csv`, clave `nflId`. Contiene displayName y officialPosition.
- `pffScoutingData.csv`, claves `gameId`, `playId` y `nflId`.
  - Contiene pff_role: Pass = QB, Pass block, Pass rush, Coverage, Pass route.
  - Para defensivos: pff_hit, pff_hurry, pff_sack.
  - Para bloqueadores: pff_hitAllowed, pff_hurryAllowed, pff_sackAllowed, pff_beatenByDefender.
- `tracking/tracking_<gameId>.csv` (en `data/data/tracking/`), **un archivo por partido**.
  - Columnas: gameId, playId, nflId, frameId, team, playDirection, x, y, s, a, dis, o, dir, event.
  - 10 cuadros por segundo.
  - El balón es la fila con `nflId` = NA y `team` = `football`.
  - Campo: x de 0 a 120 y y de 0 a 53.3.

Notas importantes:

- **Solo hay jugadas de pase** (dropbacks). No se puede comparar pase contra carrera. Las recomendaciones son entre formaciones, play action, tipos de dropback y coberturas.
- El tracking **termina cuando el QB suelta el balón o es capturado**. Los eventos útiles son:
  - Inicio: `ball_snap` (o `autoevent_ballsnap`).
  - Fin: `pass_forward` / `autoevent_passforward` (lanzó), `qb_sack` / `qb_strip_sack` (capturado) o `run` (scramble).

## Métricas

- **Tiempo en el pocket** = (frame del evento de fin − frame del snap) / 10, en segundos.
- **Tiempo hasta la presión** = primer frame después del snap en que algún defensor con `pff_role` = Pass rush está a menos de 2 yardas del QB (`pff_role` = Pass), menos el frame del snap, entre 10. Si nunca ocurre, la jugada no tuvo presión.
- **Tasa de presión permitida** de un equipo o liniero = jugadas con hit, hurry o sack permitido / jugadas en que bloqueó.
- **Situaciones de distancia:** corta (1 a 3 yardas), media (4 a 7) y larga (8 o más).
- **Éxito de una jugada:** playResult ≥ yardsToGo (logra el primer down).

## Reglas para trabajar con los datos (ahorro de tokens)

- **Nunca abras ni leas completos los CSV de `data/data/`**, sobre todo los de `tracking/`. Para conocer un archivo, usa solo los encabezados o las primeras 5 filas.
- **Al arrancar el backend:** carga solo `games`, `plays`, `players` y `pffScoutingData`, que son ligeros, y precalcula los rankings.
- **El tracking se carga bajo demanda:** solo el archivo del `gameId` que se pide, con caché en memoria (por ejemplo, `functools.lru_cache`).
- **Si falta el archivo de tracking de un partido:**
  - El visualizador muestra un mensaje amable.
  - El resto de la app sigue funcionando.
  - El dashboard solo ofrece jugadas de los partidos cuyo tracking existe.

## Endpoints previstos

- `GET /api/equipos/proteccion`: ranking de ofensivas por presión permitida.
- `GET /api/linieros/proteccion`: ranking de linieros ofensivos.
- `GET /api/defensivos/presion`: ranking de defensivos.
- `GET /api/jugadas?gameId=`: lista de jugadas de un partido, con descripción y resultado.
- `GET /api/jugada?gameId=&playId=`: devuelve:
  - los frames (posiciones de todos los jugadores y del balón),
  - los frames de snap y de fin,
  - el tiempo en el pocket,
  - el tiempo hasta la presión,
  - el resultado y las yardas.
- `GET /api/situacion?down=&yardas=`: tabla de recomendaciones sin IA.
- `POST /api/asistente`: pregunta en lenguaje natural respondida por el agente, que usa las funciones anteriores como herramientas.

## Estilo

- Interfaz en español.
- Código comentado en español y sencillo: el equipo está aprendiendo.
