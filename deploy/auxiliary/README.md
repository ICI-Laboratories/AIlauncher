# Auxiliares activos de cite-server

Configuración de producción verificada el 24 de septiembre de 2026. Las cuatro
unidades y los tres scripts de servicio coinciden por SHA-256 con los archivos
instalados; las unidades no tienen drop-ins. `models.manifest.json` contiene
repositorios, revisiones inmutables y SHA-256 cotejados con los tres archivos de
pesos activos. No se incluyen pesos, claves, archivos `.env` ni candidatos fallidos.

## Motor, GPU y contratos

Los dos procesos usan llama.cpp `runtime-10851` bajo el usuario `cite`, en
`/home/cite/auxiliary-llama`. Ambos fijan
`CUDA_VISIBLE_DEVICES=GPU-986b5314-77d6-6659-236a-6a76dbe59619` (RTX 3090),
`--device CUDA0` y `--split-mode none`. La RTX 4070 SUPER no es visible para ellos.

| Servicio | Modelo | Dirección privada | Contexto | Paralelismo |
| --- | --- | --- | --- | --- |
| OCR | GLM-OCR Q8_0 + proyector Q8_0 | `172.30.81.1:8020` | 8192 | 1 |
| Embeddings | Qwen3-Embedding-0.6B F16 | `172.30.81.1:8021` | 2048 | 1 |

OCR tiene salida máxima de 4096 tokens y límite de imagen de 4096 tokens. Las apps
renderizan una página por solicitud, hasta 1600 píxeles de lado, y usan el prompt
`Text Recognition:`. La comprobación independiente con Tesseract CPU vive en las
apps; no es otro modelo GPU. Los embeddings usan pooling `last`, normalización L2
y vectores de 1024 valores. Las apps separan documentos en fragmentos y aplican
la instrucción de búsqueda solo a las consultas.

El gateway conserva el chat existente y enruta `ocr` y `glm-ocr` a
`http://172.30.81.1:8020/v1` (`glm-ocr`) y `qwen3-embedding` a
`http://172.30.81.1:8021/v1` (`qwen3-embedding`). Configurar
`EMBEDDINGS_MAX_CONTEXT_TOKENS=2048` para reflejar el motor. Las apps llaman al
gateway con su clave; no reciben acceso directo a estos backends. Las colas OCR
y embeddings permiten una solicitud activa cada una. La configuración activa
limita OCR a una imagen de 1600 píxeles por lado, 8 MiB y salida de 4096 tokens;
embeddings admite hasta 16 textos de 8192 caracteres por solicitud. El motor
valida el contexto real de 2048 tokens: caracteres y tokens no son equivalentes.

## Margen de memoria y ciclo de vida

`gpu_guard.py` consulta la memoria libre de esa GPU cada segundo. Si baja de
3072 MiB, o falla la consulta, mata únicamente las unidades auxiliares activas
con `SIGKILL` y solicita detenerlas. Nunca administra `local-ai.service`.
Es una protección de mejor esfuerzo: no impone una cuota de VRAM y no garantiza
un mínimo instantáneo durante un pico entre sondeos. El umbral deja un margen de
reacción de 1 GiB respecto al mínimo solicitado de 2 GiB.

Ambas unidades tienen `Restart=no` y dependen de la guardia mediante `BindsTo`.
Después de una parada por presión, revisar la causa y recuperar memoria antes
de iniciar manualmente los auxiliares. OCR exige 6500 MiB libres al iniciar;
embeddings exige 6400 MiB libres después de cargar OCR. Ambos esperan a que el
chat principal esté listo y embeddings espera además al OCR. Estos controles
no cambian ni reinician el servicio principal.

## Instalación inicial y comprobación

Requiere el runtime y los pesos en las rutas indicadas, el usuario `cite`,
Python 3, `nvidia-smi`, systemd, Docker, iptables y la red privada ya existente
`llm-backend` con puente `br-llm-backend` y dirección `172.30.81.1`.
Validar UUID, rutas, hashes y puertos con `nvidia-smi`, `sha256sum` y `ss -tulpn`
antes de usar esta configuración en otro equipo.

`install_units.sh` es para instalación inicial, ejecutado como root tras copiar
las cuatro unidades y los tres scripts a `/tmp`. Rechaza puertos 8020/8021
ocupados o unidades ya existentes. Instala archivos, valida unidades, recarga
systemd e inicia solo red y guardia; no inicia ni habilita los modelos al arranque.
No ejecutarlo sobre esta instalación activa ni usarlo como actualizador.

`aux_network.sh` restringe exclusivamente los puertos privados 8020/8021 a
loopback y al puente del backend. No publica puertos en interfaces externas.
Las claves del gateway permanecen fuera de Git en `/etc/ailauncher/app-keys.json`.

Para comprobar el estado sin modificarlo:

```sh
systemctl is-active ailauncher-aux-network ailauncher-aux-guard ailauncher-ocr ailauncher-embeddings
nvidia-smi --query-gpu=uuid,name,memory.used,memory.free --format=csv
curl --fail http://127.0.0.1:8009/health
```

`/health` solo confirma vida del gateway. La aceptación funcional también exige
`/ready?model=ocr`, `/ready?model=qwen3-embedding` e inferencias autenticadas por
el gateway, registrando tiempo y VRAM. No registrar documentos ni claves. Una
reversión operativa debe detener solo `ailauncher-ocr` y `ailauncher-embeddings`,
y desactivar sus rutas/apps mediante el procedimiento controlado del gateway.
El chat principal no forma parte de esas unidades.
