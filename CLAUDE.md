# Sistema de Gestión — Kiosco

> Documento maestro del proyecto. Léelo al inicio de cada sesión de Claude Code.

## Qué es este proyecto

App web para reemplazar el Excel con el que un kiosco/almacén en Catamarca (Argentina) lleva su gestión diaria: catálogo de productos, ventas, dashboard de resultados. Reemplaza un Excel mensual de 3 hojas (Productos, Ventas, Resumen) que las socias duplican cada mes.

**Usuarias finales**: dos socias, Rita (70%) y Gaby (30%), no técnicas. Cargan ventas desde el celular detrás del mostrador.

**Deploy target**: Streamlit Community Cloud (free tier).

## Stack

- **Streamlit** — UI + lógica, todo Python, un proceso.
- **SQLAlchemy 2.0** — ORM. Mismo código corre contra SQLite (dev local) y Postgres (Supabase, prod).
- **Pandas** — script de migración del Excel + agregaciones del dashboard.
- **Plotly** — gráficos del dashboard.
- **openpyxl** — leer el Excel original.
- **psycopg2-binary** — driver Postgres para Supabase.
- **python-dotenv** — manejo de variables de entorno en dev (opcional, `st.secrets` cubre lo demás).

Python 3.11+.

## Decisiones tomadas (NO revisar sin avisar al usuario)

1. **Sistema continuo, no mensual.** Una sola tabla de ventas, filtrada por rango de fechas. NO replicar el modelo "duplicar hojas por mes" del Excel.
2. **Fiado con notas libres**, sin tabla de clientes en v0. Campo de texto. Ej: "Juan del kiosco", "María - debe 5000".
3. **Sin arqueo de caja** en v0.
4. **Sin multi-usuario** en v0. Una contraseña compartida en `st.secrets["APP_PASSWORD"]`. Las dos socias entran con la misma.
5. **Split 70/30 hardcoded** en `config.py`. Rita 0.70, Gaby 0.30.
6. **Mobile-first.** Layout wide en `.streamlit/config.toml` y diseño que respire en pantalla angosta.
7. **Snapshot de precio y costo en cada venta.** `sales.unit_price_snapshot` y `sales.unit_cost_snapshot` se copian del producto al momento de guardar la venta. **NUNCA se recalculan** a partir del producto actual.
8. **Stock calculado, no almacenado.** `stock_actual(product) = SUM(stock_movements.quantity_delta) - SUM(sales.quantity)` para ese producto. La migración inicial inserta un `stock_movement` por producto con `reason="Carga inicial desde Excel"`.
9. **`price_history` es para auditar el catálogo, no para calcular ventas.** Las ventas son inmutables vía sus snapshots. `price_history` solo registra cambios en `products.current_cost` o `products.current_sale_price`.
10. **Fechas**: en BD siempre en UTC. Convertir a `America/Argentina/Catamarca` solo en la UI.

## Modelo de datos (DDL portable SQLite/Postgres)

```sql
CREATE TABLE categories (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    code_prefix   VARCHAR(2) NOT NULL UNIQUE
);

CREATE TABLE products (
    id                    INTEGER PRIMARY KEY,
    code                  TEXT NOT NULL UNIQUE,
    name                  TEXT NOT NULL,
    category_id           INTEGER NOT NULL REFERENCES categories(id),
    is_weighted           BOOLEAN NOT NULL DEFAULT FALSE,
    current_cost          NUMERIC(12, 2) NOT NULL DEFAULT 0,
    current_sale_price    NUMERIC(12, 2) NOT NULL DEFAULT 0,
    active                BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_active   ON products(active);

CREATE TABLE price_history (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    cost            NUMERIC(12, 2) NOT NULL,
    sale_price      NUMERIC(12, 2) NOT NULL,
    effective_from  TIMESTAMP NOT NULL,
    effective_to    TIMESTAMP
);
CREATE INDEX idx_price_history_product ON price_history(product_id);

CREATE TABLE sales (
    id                    INTEGER PRIMARY KEY,
    sold_at               TIMESTAMP NOT NULL,
    product_id            INTEGER NOT NULL REFERENCES products(id),
    quantity              NUMERIC(10, 3) NOT NULL CHECK (quantity > 0),
    unit_price_snapshot   NUMERIC(12, 2) NOT NULL,
    unit_cost_snapshot    NUMERIC(12, 2) NOT NULL,
    payment_method        TEXT NOT NULL CHECK (payment_method IN ('efectivo','transferencia','fiado')),
    fiado_note            TEXT,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sales_sold_at ON sales(sold_at);
CREATE INDEX idx_sales_product ON sales(product_id);
CREATE INDEX idx_sales_payment ON sales(payment_method);

CREATE TABLE stock_movements (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    quantity_delta  NUMERIC(10, 3) NOT NULL,
    reason          TEXT NOT NULL,
    occurred_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes           TEXT
);
CREATE INDEX idx_stock_movements_product ON stock_movements(product_id);
```

## Categorías canónicas (12) y prefijos de código

| Categoría    | Prefijo |
|--------------|:-------:|
| Almacen      | A       |
| Bebidas      | B       |
| Farmacia     | F       |
| Golosinas    | G       |
| Helados      | H       |
| Libreria     | LI      |
| Limpieza     | L       |
| Otros        | O       |
| Perfumeria   | P       |
| Repuesto     | R       |
| Snack        | S       |
| Verduras     | V       |

**OJO**: `Libreria` usa 2 letras (LI). El resto, 1. `Limpieza` (L) y `Libreria` (LI) comparten primera letra: cualquier parser que deduzca categoría desde el código debe matchear LI **antes** que L.

## Estructura del repo

```
kiosco-app/
├── app.py                          # Home: KPIs de hoy + botón a "Nueva Venta"
├── pages/
│   ├── 1_Cargar_Venta.py
│   ├── 2_Dashboard.py
│   └── 3_Productos.py
├── db.py                           # engine SQLAlchemy, session factory, init_db()
├── models.py                       # Category, Product, PriceHistory, Sale, StockMovement
├── queries.py                      # funciones de agregación
├── auth.py                         # check_password() con st.secrets
├── config.py                       # constantes (split, métodos de pago, categorías)
├── migrate_excel.py                # CLI: python migrate_excel.py --excel ... --db-url ...
├── requirements.txt
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── data/
│   ├── raw/
│   │   └── CONTROL_DEL_KIOSCO1.xlsx   # NO commitear, gitignored
│   └── .gitkeep
├── .gitignore
├── CLAUDE.md
└── README.md
```

## Datos del Excel — gotchas conocidos

- Hoja relevante para migrar: **`Catálogo Export`** (625 productos, ya normalizada por el contador).
- Columna `categoria_normalizada` ya tiene las 12 categorías canónicas. La columna `categoria_original` se preserva solo para auditoría (logueá la diferencia si querés, pero usá `categoria_normalizada` para la inserción).
- 3 códigos duplicados marcados con sufijo `-DUP`: `B066-DUP`, `G053-DUP`, `O033-DUP`. Insertarlos tal cual con su sufijo. No mergear con su gemelo.
- 0 nulos, 0 stock negativo, 0 mixed-case en códigos. Los datos vienen limpios.
- `stock_inicial` y `costo` vienen como `float`; `precio_venta` como `int`. Castear todo a `NUMERIC` en BD.
- El migrate debe insertar para cada producto un `stock_movement` con `quantity_delta = stock_inicial`, `reason = "Carga inicial desde Excel"`, `occurred_at = NOW()`. Si no, el stock arranca en 0.

## Alcance v0 — qué entra

- **Home (`app.py`)**: KPIs de hoy (ventas totales, ganancia, ventas por método de pago, últimas 5 ventas), botón grande "➕ Nueva Venta".
- **Página 1 — Cargar Venta**: selector/autocompletado de producto por código o nombre, muestra precio y stock, input cantidad (decimales), radio método de pago, si fiado: nota libre, botón Guardar. Muestra las últimas 5 ventas del día como confirmación visual. **Objetivo: 10 segundos por venta en mobile.**
- **Página 2 — Dashboard**: rango de fechas (default = hoy). KPIs: total ventas, ganancia, ganancia Rita 70%, ganancia Gaby 30%, ventas por método. Gráfico de línea ventas/ganancia por día. Top 10 productos del período.
- **Página 3 — Productos**: tabla editable con búsqueda por código/nombre y filtro por categoría. Botón "Nuevo producto". Al editar precio o costo, escribir snapshot en `price_history`.

## Alcance v0 — qué NO entra

- Multi-usuario / roles
- Arqueo de caja
- Tabla de clientes / cuentas por cobrar formales
- Compras / órdenes a proveedores
- Reportes fiscales
- Exportación a PDF
- Notificaciones / WhatsApp
- App móvil nativa

## Criterios de éxito v0

1. Cargar una venta en ≤ 10 segundos desde un celular.
2. Los totales diarios del dashboard cuadran al 1% con el Excel (corrida en paralelo durante 1 semana).
3. La app funciona en celular sin pellizcar zoom.

## Reglas para vos, Claude Code

1. **No improvisar arquitectura.** Si una decisión no está en este documento, **paráte y preguntá** al usuario antes de codear. No inventes tablas, no inventes flujos, no agregues columnas.
2. **No tocar este `CLAUDE.md`** salvo que el usuario lo pida explícitamente.
3. **Antes de crear cada archivo nuevo**, contale al usuario qué vas a hacer y por qué. El usuario es contador, no dev. Explicá en castellano claro.
4. **Después de crear cada archivo**, mostralo, esperá ok, recién entonces seguí al siguiente.
5. **No instales paquetes sin actualizar `requirements.txt`** en la misma operación.
6. **No commits automáticos.** El usuario decide cuándo hacer `git commit` y qué incluir.
7. **No corras `migrate_excel.py` sin avisar.** Es destructivo si se corre dos veces sin reset. Avisá y esperá ok explícito.
8. **Cuando algo del Excel no calce con este doc**, paráte y consultá. NO improvisar parseo.
9. **Errores de Python**: explicáselos al usuario en castellano simple antes de proponer el fix.
10. **Tests automáticos**: no escribir en v0. Validar a ojo con datos reales.

## Orden de implementación sugerido

1. `requirements.txt`
2. `db.py`
3. `models.py`
4. `config.py`
5. `migrate_excel.py`
6. **CHECKPOINT**: correr migrate contra SQLite local. Validar 625 productos y 12 categorías. Mostrar conteos.
7. `auth.py`
8. `queries.py`
9. `.streamlit/config.toml` y `.streamlit/secrets.toml.example`
10. `app.py` (Home)
11. `pages/1_Cargar_Venta.py`
12. **CHECKPOINT**: probar local `streamlit run app.py`, cargar 3 ventas de prueba, confirmar que se guardan.
13. `pages/2_Dashboard.py`
14. `pages/3_Productos.py`
15. **CHECKPOINT FINAL**: app local 100% funcional con datos reales del Excel.

## Cuando el usuario diga "deployemos"

1. Verificar que `requirements.txt` está completo y la app corre local sin errores.
2. Verificar que `data/` y `.streamlit/secrets.toml` están en `.gitignore`.
3. `git push` a `main`.
4. En Streamlit Cloud: New app → conectar repo → `app.py` como entrypoint.
5. En Streamlit Cloud → Settings → Secrets, cargar `APP_PASSWORD` y `DB_URL` (URI del **Transaction Pooler** de Supabase, puerto 6543).
6. Deploy. Verificar que abre y la contraseña funciona.
7. **El migrate corre desde local apuntando a la `DB_URL` de Supabase, una sola vez.** No correrlo desde Streamlit Cloud.
