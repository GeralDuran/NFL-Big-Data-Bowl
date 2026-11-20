# PocketClock AI — Sincronía de Protección y Ventana de Pase

## Resumen ejecutivo

**Usuario objetivo:** coordinadores ofensivos y coaches de línea ofensiva y de receptores. Hoy no tienen una métrica que una el tiempo de protección con la ventana de pase que se abre. PocketClock AI crea el **Índice PSI = Target Window Separation ÷ Pocket Collapse Time**: yardas de separación del receptor más abierto por cada segundo de bolsillo. En 122 partidos y 8,557 jugadas de pase, la presión llega antes del pase en el 51.7% de las jugadas: el bolsillo colapsa a los 2.32 s y el lanzamiento tarda 2.94 s. El Play Action eleva el PSI de 2.99 a 3.83 y suma +1.66 yardas por jugada.

## Visualización

![Film Room 2D](docs/filmroom.png)

![Simulador Play-Caller](docs/simulator.png)

## Ejecución y Despliegue

Se asume que las dependencias de `requirements.txt` y `node_modules` ya están instaladas y que la carpeta `data/` está montada en la raíz del proyecto.

1. Preprocesamiento (opcional, el resultado ya está incluido en `backend/data_summary.json`):

   ```bash
   python -m backend.precompute
   ```

2. Compilación del frontend:

   ```bash
   cd dashboard && npm run build && cd ..
   ```

3. Arranque del servidor FastAPI en el puerto 8000. Sirve la API (`/api/*`) y los estáticos compilados de `dashboard/dist`:

   ```bash
   uvicorn backend.main:app --port 8000
   ```
