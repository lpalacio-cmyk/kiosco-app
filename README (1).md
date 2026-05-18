# Sistema de Gestión — Kiosco

App web en Streamlit para administrar el día a día de un kiosco/almacén: catálogo de productos, carga de ventas y dashboard de resultados. Reemplaza un sistema basado en Excel.

## Stack

- Python 3.11+
- Streamlit (UI)
- SQLAlchemy 2.0 (ORM)
- SQLite (desarrollo local) / Postgres en Supabase (producción)
- Pandas + Plotly (dashboard)

## Setup local

### 1. Clonar el repo

```bash
git clone https://github.com/<tu-usuario>/kiosco-app.git
cd kiosco-app
```

### 2. Crear y activar el entorno virtual

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar secrets locales

Copiar el template y completar los valores:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Editar `.streamlit/secrets.toml`:

```toml
APP_PASSWORD = "una-clave-fuerte"
DB_URL = "sqlite:///data/kiosco.db"
```

> El archivo `secrets.toml` está en `.gitignore`. **Nunca** lo commitees.

### 5. Cargar el catálogo inicial desde el Excel

Colocar el Excel original en `data/raw/CONTROL_DEL_KIOSCO1.xlsx` (no commitearlo, contiene datos del cliente). Luego:

```bash
python migrate_excel.py --excel data/raw/CONTROL_DEL_KIOSCO1.xlsx --db-url "sqlite:///data/kiosco.db"
```

El script crea las tablas (si no existen), inserta las 12 categorías, los 625 productos y un movimiento de stock inicial por cada producto. Loguea a `stdout` cuántas filas insertó y qué quedó pendiente de revisión manual.

### 6. Levantar la app

```bash
streamlit run app.py
```

La app abre en `http://localhost:8501`.

## Deploy a Streamlit Community Cloud

### 1. Crear proyecto en Supabase

- Crear un proyecto nuevo en [supabase.com](https://supabase.com).
- En **Project Settings → Database → Connection pooling**, modo **Transaction**, copiar la URI.
- La URI tiene el formato `postgresql://postgres.xxx:[YOUR-PASSWORD]@aws-0-xxx.pooler.supabase.com:6543/postgres`. Reemplazar `[YOUR-PASSWORD]` por la contraseña real del proyecto.

> Importante: usar la URI del **Transaction Pooler (6543)**, no la directa (5432). Streamlit Cloud reinicia el contenedor seguido y la directa se queda sin conexiones.

### 2. Migrar el catálogo a Supabase

Desde tu máquina local (no desde Streamlit Cloud):

```bash
python migrate_excel.py --excel data/raw/CONTROL_DEL_KIOSCO1.xlsx --db-url "postgresql://postgres.xxx:..."
```

### 3. Deployar en Streamlit Cloud

- Pushear el repo a GitHub.
- En [share.streamlit.io](https://share.streamlit.io), **New app** → seleccionar el repo y `app.py` como entrypoint.
- En **Settings → Secrets**, cargar:
  ```toml
  APP_PASSWORD = "una-clave-fuerte"
  DB_URL = "postgresql://postgres.xxx:..."
  ```
- Deploy.

## Estructura del repo

```
kiosco-app/
├── app.py                          # Home
├── pages/                          # páginas Streamlit
│   ├── 1_Cargar_Venta.py
│   ├── 2_Dashboard.py
│   └── 3_Productos.py
├── db.py                           # engine SQLAlchemy
├── models.py                       # modelos ORM
├── queries.py                      # agregaciones del dashboard
├── auth.py                         # contraseña compartida
├── config.py                       # constantes (split socias, categorías, métodos de pago)
├── migrate_excel.py                # script CLI de migración inicial
├── requirements.txt
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── data/                           # SQLite local + Excel original (gitignored)
├── CLAUDE.md                       # contexto técnico del proyecto
└── README.md
```

## Mantenimiento

### Agregar un producto nuevo

Desde la app: **Productos → Nuevo producto**. Se carga con stock inicial 0 — usar el módulo de movimientos de stock (futura versión) o cargar un `stock_movement` directo en BD.

### Actualizar precios

Desde la app: **Productos → editar fila**. El sistema escribe un snapshot en `price_history` automáticamente. Las ventas pasadas **no se recalculan**: cada venta guarda el precio y costo al momento.

### Backup

Para SQLite: copiar el archivo `data/kiosco.db`. Para Supabase: usar el dump automático del proyecto o exportar manualmente desde el panel.

### Auditoría

Las ventas son inmutables. Para corregir una venta cargada por error, marcar el caso y resolver desde la BD con un asiento de ajuste. No editar la tabla `sales` directamente desde la UI.

## Licencia

Privado.
