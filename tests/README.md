Para que la batería de pruebas quede clara y fácil de ampliar, armemos primero un **README** dentro de la carpeta `tests/`.
Luego te iré entregando cada archivo de test ( `conftest.py`, `test_cli.py`, etc. ) uno por uno; solo dime **“siguiente”** cada vez que quieras el siguiente.

---

### `tests/README.md`

```markdown
# Carpeta `tests/` – PyTest suite

Esta carpeta contiene las **pruebas automáticas** de LMServ.  
Objetivos:

1. Verificar que la CLI y la API respondan con los parámetros por defecto.
2. Asegurar que el `WorkerPool` lanza procesos `llama-cli` y hace streaming.
3. Mantener tiempos de prueba razonables (≤ 10 s totales en CI).

```

tests/
├── conftest.py            # fixtures comunes
├── test\_cli.py            # sub-comandos Typer
├── test\_api.py            # /health y /chat (httpx AsyncClient)
├── test\_worker\_pool.py    # spawn / infer / teardown
└── test\_discovery.py      # discover\_nodes() con monkeypatch

````

## Dependencias de test

```bash
pip install pytest pytest-asyncio httpx
````

> **Nota**
> Los tests **mockean** la llamada a `subprocess.Popen` para no requerir
> `llama-cli` real; así la suite corre en cualquier CI.

## Ejecutar

```bash
pytest -q
```

## Tiempo aproximado

| Archivo               | Duración |
| --------------------- | -------- |
| `test_cli.py`         | < 1 s    |
| `test_api.py`         | 2–3 s    |
| `test_worker_pool.py` | 3–4 s    |
| `test_discovery.py`   | 1 s      |

---

## Cambios recientes

| Fecha      | Autor       | Descripción                          |
| ---------- | ----------- | ------------------------------------ |
| 2024-07-03 | @tu-usuario | Primera versión de la suite de tests |

## Pendiente

* [ ] Cobertura para `cpp_bridge` (cuando exista la lib C++).
* [ ] Test end-to-end con PyInstaller one-file.

```

Cuando quieras el **primer archivo real** ( `conftest.py` ), dime **“siguiente”**.
```
