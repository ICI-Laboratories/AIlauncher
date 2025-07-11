
# `lmserv/install` – setup helpers

Este paquete automatiza **todo el “primer día”**: compilar `llama.cpp`
y descargar modelos en formato `.gguf`, de forma reproducible y
verificada.

```

install/
├── **init**.py      # re-exporta build\_llama\_cpp, download\_models
├── llama\_build.py   # build cross-plataforma (CPU / CUDA)
└── models\_fetch.py  # catálogo y fetch de modelos con checksum

````

---

## Comandos rápidos

```bash
# compilar llama.cpp con CUDA (auto-detect)
lmserv install llama --output-dir build/

# bajar dos modelos verificados a la carpeta models/
lmserv install models gemma-2b phi3-mini --target-dir models/
````

`llama_build.py` es **idempotente**: si ya existe
`build/bin/llama-cli` salta la compilación.

---

## Detalles de implementación

| Archivo              | Puntos clave                                                                                                                            |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **llama\_build.py**  | • Clona repo oficial<br>• Detecta OS: `make` (Linux/macOS) o `CMake+MSVC` (Windows)<br>• Flags `LLAMA_CUBLAS=1` cuando `--cuda`         |
| **models\_fetch.py** | • Catálogo `_CATALOG` con URL + SHA-256<br>• Descarga con *resume* (`Range` header)<br>• Verifica checksum y descomprime `.tar.gz/.zst` |

Añadir un nuevo modelo ≈ 3 líneas en `_CATALOG`
(`"alias": ("url", "sha256")`).

---

## Variables de entorno relevantes

| ENV                          | Default   | Uso                                                   |
| ---------------------------- | --------- | ----------------------------------------------------- |
| `GIT_SSL_NO_VERIFY`          | *(vacío)* | Si tu red usa MITM, pon `true` para saltar TLS verify |
| `HTTP_PROXY` / `HTTPS_PROXY` |           | Descargas vía proxy corporativo                       |

---

## Cambios recientes

| Fecha        | Autor       | Descripción                                 |
| ------------ | ----------- | ------------------------------------------- |
| 2024-06-\*\* | @tu-usuario | Añadido soporte *resume* + checksum SHA-256 |

---

## Pendiente

* [ ] Soporte para modelos **LoRA** (mezcla durante descarga).
* [ ] Publicar hashes **SHAKE-256** para archivos >4 GB.
* [ ] Script `uninstall` que limpie binarios y modelos.

