
# Carpeta `docs/` – assets y documentación adicional

Aquí reunimos **diagramas, banners, especificaciones y apuntes** que no
forman parte del paquete de código pero sí ayudan a entender la
arquitectura y a mantenerla en el tiempo.

```

docs/
├── banner.svg           # cabecera usada en README principal
├── diagram.svg          # “big-picture”: CLI → API → WorkerPool
├── discovery-seq.svg    # secuencia mDNS announce / browse / registry
├── api-openapi.json     # snapshot del esquema FastAPI (generado)
└── contrib/             # borradores, RFCs, notas de diseño

````

## Cómo generar / actualizar los diagramas

1. **Excalidraw**  
   Los `.svg` provienen de `.excalidraw` almacenados en
   `docs/contrib/`.  Abre el archivo en  
   https://excalidraw.com → `Export → SVG`.

2. **Graphviz**  
   Si prefieres `.dot`, coloca el fuente `*.dot` junto al `.svg` y
   documenta el comando:

   ```bash
   dot -Tsvg docs/diagram.dot -o docs/diagram.svg
````

3. **OpenAPI spec**
   Cada vez que añadas un endpoint:

   ```bash
   # estando en raíz del proyecto (venv activado)
   python -m uvicorn lmserv.server.api:app --port 9000 &
   sleep 2
   curl http://localhost:9000/openapi.json > docs/api-openapi.json
   pkill -f "uvicorn .*9000"
   ```

## Buenas prácticas

| Tipo de archivo      | Recomendación                                                        |
| -------------------- | -------------------------------------------------------------------- |
| **SVG**              | Preferible sobre PNG para que diffs sean legibles en PRs.            |
| **Imágenes grandes** | Usa `docs/assets/` si superan 1 MB.                                  |
| **RFCs**             | Numera: `rfc-001-nombre.md` con plantilla título / estado / resumen. |
| **Changelogs**       | Se llevan por carpeta (`server/README.md` etc.), no aquí.            |

## Cambios recientes

| Fecha        | Autor       | Descripción                                             |
| ------------ | ----------- | ------------------------------------------------------- |
| 2024-06-\*\* | @tu-usuario | Primer diagrama de arquitectura añadido (`diagram.svg`) |
| 2024-06-\*\* | @compañero  | Banner `banner.svg` para README principal               |

## Pendiente

* [ ] Automatizar export de OpenAPI a **Redoc** HTML.
* [ ] Agregar un diagrama de secuencia para `WorkerPool`.
* [ ] Documentar política de versionado de modelos (.gguf).
