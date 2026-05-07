# Titulo del Trabajo

LMLauncher: gateway local y escalable para integrar aplicaciones con multiples motores LLM

## Autores

| Campo | Especificacion |
|---|---|
| Nombre del autor | Pendiente |
| Correo electronico | Pendiente |

**Contacto:**
- Correo: `pendiente@institucion.mx`
- Telefono con lada: Pendiente

**Semblanza:** Pendiente.

## RESUMEN

La integracion de aplicaciones con modelos de lenguaje de gran tamano aun presenta barreras para investigadores, laboratorios y pequenas empresas que desean operar con infraestructura local o hibrida. Cada motor de inferencia expone diferencias de protocolo, capacidades y configuracion, lo que obliga a mantener adaptadores especificos. Este trabajo presenta LMLauncher, una arquitectura de gateway local que desacopla a las aplicaciones consumidoras del motor subyacente mediante una interfaz compatible con OpenAI, un catalogo de modelos y un resolvedor de capacidades para enrutar solicitudes hacia backends como `llama.cpp` y Ollama. La validacion se realizo sobre un servidor con dos GPU NVIDIA RTX A4000 y un perfil Ollama optimizado para SARA (`qwen3.6-sara:opt`). El prototipo respondio correctamente solicitudes autenticadas, `json_object`, `json_schema`, generacion larga y concurrencia ligera. En ruta caliente, `json_schema` obtuvo 1.597 s de latencia media y las generaciones de 256 y 512 tokens alcanzaron 37.53 y 40.26 tokens/s de pared. La contribucion principal es una base reproducible para integrar aplicaciones LLM locales con menor acoplamiento, salida estructurada validable y una ruta clara hacia perfiles de ejecucion por hardware.

**PALABRAS CLAVE:** despliegue local de LLM, gateway de inferencia, interoperabilidad, optimizacion GPU, salida estructurada

## ABSTRACT

Integrating applications with large language models still creates barriers for researchers, laboratories, and small businesses that need local or hybrid infrastructure. Each inference engine exposes different protocols, capabilities, and configuration options, forcing teams to maintain engine-specific adapters. This work presents LMLauncher, a local gateway architecture that decouples client applications from the underlying inference engine through an OpenAI-compatible interface, a model catalog, and a capability resolver that routes requests to backends such as `llama.cpp` and Ollama. Validation was performed on a server with two NVIDIA RTX A4000 GPUs using an Ollama profile optimized for SARA (`qwen3.6-sara:opt`). The prototype successfully handled authenticated requests, `json_object`, `json_schema`, long generation, and light concurrency. On the warm path, `json_schema` reached a mean latency of 1.597 s, while 256-token and 512-token generations reached 37.53 and 40.26 wall-clock tokens/s. The main contribution is a reproducible foundation for integrating local LLM applications with lower coupling, verifiable structured outputs, and a clear path toward hardware-aware execution profiles.

**KEYWORDS:** GPU optimization, inference gateway, interoperability, local LLM serving, structured outputs

## 1. INTRODUCCION

El uso de modelos de lenguaje en aplicaciones cientificas, asistentes internos, plataformas de analisis y herramientas empresariales ha crecido aceleradamente; sin embargo, una parte importante de estas soluciones continua dependiendo de APIs propietarias o de adaptaciones especificas para cada motor de inferencia [1], [2]. Este escenario es especialmente problematico para investigadores y pequenas empresas, ya que el costo de integracion no reside unicamente en ejecutar un modelo, sino en mantener compatibilidad entre clientes, motores, formatos de respuesta y mecanismos de escalado [3], [4].

La hipotesis de este trabajo es que una arquitectura de gateway, basada en compatibilidad de protocolo, resolucion explicita de capacidades y perfiles de ejecucion por backend, puede reducir el costo de integracion y mejorar la continuidad operativa de aplicaciones que consumen LLM locales o auto hospedados. En particular, se plantea que la seleccion automatica de rutas ante solicitudes con requisitos especificos, como `structured output`, puede ocultar diferencias funcionales del motor y mantener una interfaz estable para el usuario final [4], [5].

El objetivo general es disenar y prototipar una base de software llamada LMLauncher que permita a diferentes aplicaciones conectarse a multiples motores LLM mediante una sola URL y una interfaz estable. Los objetivos especificos son: a) definir un catalogo de modelos, alias, capacidades y parametros de runtime, b) implementar un resolvedor de rutas con fallback automatico, c) exponer una interfaz de compatibilidad para clientes existentes, d) validar salida estructurada y rendimiento en un servidor real y e) documentar una ruta de evolucion hacia escalamiento horizontal, observabilidad y seleccion por perfil de hardware.

## 2. REVISION DE LA LITERATURA

La literatura reciente sobre servicio de LLM se ha concentrado fuertemente en el rendimiento del motor de inferencia y en la eficiencia del uso de memoria. vLLM introdujo `PagedAttention` para mejorar el manejo de memoria KV y elevar el throughput en escenarios multiusuario [6]. En la misma linea, sistemas como SGLang han explorado optimizaciones orientadas a programacion de inferencia, batching y composicion de flujos de generacion [7]. Estas propuestas son fundamentales para el rendimiento, pero no resuelven por si mismas el problema de interoperabilidad entre aplicaciones cliente y motores heterogeneos.

En el ecosistema practico, `llama.cpp` se ha consolidado como uno de los motores locales mas accesibles para ejecutar modelos cuantizados en hardware de consumo [8]. `Ollama`, por su parte, ha simplificado la operacion de modelos locales mediante una API estable y, mas recientemente, ha incorporado soporte para salidas estructuradas y compatibilidad parcial con el ecosistema OpenAI [3], [4], [5]. Estas herramientas facilitan la ejecucion, pero trasladan a los usuarios la decision de que backend usar y como lidiar con diferencias funcionales entre ellos.

La disponibilidad de modelos abiertos especializados, como Code Llama y Llama 3, ha impulsado ademas escenarios donde laboratorios y pequenas organizaciones desean controlar localmente inferencia, datos y costos [11], [12]. Al mismo tiempo, plataformas de servicio como BentoML muestran que el patron de gateway es relevante para desplegar y gobernar inferencia en ambientes de produccion [13]. LMLauncher se ubica en ese espacio, pero con enfasis en infraestructura local, compatibilidad para clientes existentes y declaracion explicita de capacidades por ruta.

En paralelo, la adopcion de salidas estructuradas ha tomado relevancia porque una gran parte de las aplicaciones ya no solo requiere texto libre, sino respuestas validadas contra esquemas JSON, extraccion de entidades y contratos de datos para automatizacion [1], [5], [9]. Aun asi, la disponibilidad de esta capacidad depende del motor, del modelo y del protocolo expuesto. Esto justifica un enfoque de gateway con resolucion por capacidades en lugar de un simple proxy estatico.

## 3. MATERIAL Y METODOS

El trabajo se desarrolla sobre un prototipo de software en Python denominado LMLauncher. La implementacion base utiliza FastAPI como capa HTTP [10] y se ejecuta sobre infraestructura local o de laboratorio, con posibilidad de conectarse a motores `llama.cpp` mediante procesos persistentes y a instancias de Ollama mediante HTTP. El entorno de trabajo corresponde a una arquitectura reproducible desde repositorio fuente, con configuracion por variables de entorno y un catalogo JSON de modelos.

Metodologicamente, se adopto un diseno incremental orientado por arquitectura. Primero se reviso el servidor original para identificar acoplamientos fuertes entre API y backend. Despues se introdujeron tres componentes: un catalogo de modelos con capacidades anunciadas, un resolvedor de rutas y una capa de runtimes por backend. Finalmente, se anadio una interfaz `/v1/chat/completions` compatible con clientes estilo OpenAI para reducir el costo de adopcion por parte de aplicaciones existentes.

La logica experimental se centra en solicitudes conversacionales y en peticiones con `response_format`. Para cada solicitud, LMLauncher identifica el modelo solicitado o el modelo por defecto, evalua si cubre capacidades como `structured_output`, `json_mode` o `tools` y, si no lo hace, busca una ruta alternativa compatible. El resultado de esta evaluacion se refleja en un enrutamiento transparente al backend seleccionado. El mecanismo de fallback se valido a nivel de componente mediante pruebas unitarias del catalogo y del resolvedor; el despliegue productivo de SARA, en cambio, usa una sola ruta optimizada que ya anuncia las capacidades requeridas, por lo que no activa fallback durante las pruebas productivas reportadas.

La validacion productiva se ejecuto el 7 de mayo de 2026 en un servidor Ubuntu 24.04.4 LTS virtualizado sobre VMware, con 24 vCPU Intel Xeon E5-2640, 19 GiB de RAM y dos GPU NVIDIA RTX A4000. El gateway `ailauncher` se ejecuto en el puerto 8009 y Ollama sirvio el modelo derivado `qwen3.6-sara:opt`. El catalogo productivo fijo `think=false`, `num_ctx=4096`, `num_gpu=41`, `num_batch=512`, `num_thread=24` y `keep_alive=24h`. Antes de la medicion, `ollama ps` reporto el modelo residente como `100% GPU`, contexto 4096 y permanencia de 24 horas.

El protocolo de prueba incluyo verificacion de servicios (`ailauncher`, Ollama, Docker y SARA), acceso a `/health`, acceso autenticado a `/v1/models`, tres repeticiones de respuesta exacta, tres repeticiones de `json_schema`, tres repeticiones de `json_object`, tres generaciones controladas de 256 tokens, dos generaciones tipo evaluacion de 512 tokens y una prueba concurrente de dos solicitudes. Para cada corrida se registro latencia de pared, tokens generados, tokens por segundo, modelo seleccionado, validez JSON y estado posterior de servicios. Los artefactos quedaron almacenados en `/srv/ai-data/ailauncher/experiments/paper-validation-final-20260507T064642Z`.

**Figura 1: Arquitectura propuesta de LMLauncher.**  
Fuente: Elaboracion propia.

1. Aplicacion cliente o herramienta investigadora
2. API gateway compatible
3. Catalogo de modelos y capacidades
4. Resolvedor de rutas
5. Runtime `llama.cpp`
6. Runtime `Ollama`
7. Futuro plano de orquestacion horizontal

**Tabla 1. Componentes funcionales del prototipo.**

| Componente | Funcion principal |
|---|---|
| API Gateway | Expone una interfaz estable para aplicaciones externas |
| Catalogo | Declara backends, alias y capacidades por modelo |
| Resolvedor | Selecciona la mejor ruta disponible segun requisitos |
| Runtime `llama.cpp` | Ejecuta modelos GGUF locales con workers persistentes |
| Runtime `Ollama` | Consume modelos locales o remotos mediante HTTP |

Fuente: Elaboracion propia.

## 4. RESULTADOS

El principal resultado de esta etapa es la transformacion del proyecto desde un servidor acoplado a `llama.cpp` hacia una base de gateway multi-backend. La nueva arquitectura introduce un punto de entrada compatible con clientes tipo OpenAI, de manera que una aplicacion existente puede integrarse cambiando principalmente `base_url` y credenciales. Esto reduce la necesidad de construir una capa API especifica para cada motor o caso de uso.

Tambien se implemento un catalogo de modelos que permite declarar rutas con alias, backend, capacidades y parametros de runtime. Este mecanismo habilita que un modelo principal sea preferido para conversacion general y que otra ruta sea reservada para tareas que requieren salida estructurada o soporte de herramientas. En las pruebas unitarias, el resolvedor selecciono automaticamente una ruta alternativa cuando la ruta principal no anunciaba `structured_output`. En el despliegue productivo de SARA, la ruta `sara-main` ya cubre las capacidades requeridas, por lo que todas las solicitudes medidas fueron atendidas por esa misma ruta.

El catalogo productivo validado usa `qwen3.6-sara:opt`, derivado de `qwen3.6:35b`, servido por Ollama con `num_ctx=4096`, `num_gpu=41`, `num_batch=512`, `num_thread=24`, `think=false` y `keep_alive=24h`. Durante la validacion final, el modelo permanecio residente como `100% GPU` en dos RTX A4000; el uso de memoria reportado fue 11582 MiB en la primera GPU y 14368 MiB en la segunda. El gateway respondio `/health` y `/v1/models` autenticado con codigo 200, y despues de la prueba el sistema se mantuvo en estado `running`, sin unidades fallidas.

**Tabla 2. Validacion productiva de LMLauncher con `qwen3.6-sara:opt`.**

| Prueba | n | Latencia media | Rango | Tokens/s medio | Resultado |
|---|---:|---:|---:|---:|---|
| `sanity_ok` | 3 | 1.027 s | 1.009-1.050 s | 1.95 | `OK` exacto 3/3 |
| `json_schema` | 3 | 1.597 s | 1.456-1.721 s | 13.21 | JSON valido 3/3 |
| `json_object` | 3 | 1.739 s | 1.632-1.830 s | 12.10 | JSON valido 3/3 |
| `controlled_256` | 3 | 6.826 s | 6.584-7.004 s | 37.53 | HTTP 200 3/3 |
| `assessment_like_512` | 2 | 12.718 s | 12.656-12.779 s | 40.26 | HTTP 200 2/2 |
| `concurrent_2` | 2 | 3.815 s | 2.795-4.835 s | 23.44 | HTTP 200 2/2 |

Fuente: Elaboracion propia.

La primera solicitud fria registrada ese dia tomo 53.319 s, asociada a la carga inicial del modelo. Una vez caliente, las solicitudes de salida estructurada se mantuvieron entre 1.4 y 1.8 s, y las generaciones de 256 a 512 tokens se mantuvieron alrededor de 37 a 40 tokens/s de pared. La prueba concurrente de dos solicitudes completo el par en 4.844 s.

Como prueba exploratoria adicional de optimizacion por hardware, se compilo una version de `llama.cpp` con CUDA dentro de un contenedor aislado para las GPUs NVIDIA RTX A4000, usando arquitectura `sm_86`. La compilacion no modifico los servicios de produccion y genero binarios `llama-cli`, `llama-server` y `llama-bench`. Con el modelo `qwen3:30b` cuantizado en Q4_K_M, `llama-bench` mostro una diferencia sustancial entre una configuracion con 4 capas en GPU y una configuracion con offload alto: la generacion paso de 0.67 tokens/s a 93.31 tokens/s en una prueba pequena de 16 tokens generados. Este resultado no sustituye la validacion productiva de SARA, pero confirma que el grado de offload a GPU es una variable critica para el rendimiento del sistema.

## 5. DISCUSION DE RESULTADOS

Los resultados muestran que el problema de interoperabilidad en despliegues locales de LLM no se resuelve unicamente con un motor eficiente. Trabajos como vLLM y SGLang atacan con exito el problema del rendimiento [6], [7], pero el acoplamiento entre aplicaciones y motores sigue siendo una barrera cuando el objetivo es servir multiples herramientas con minimos cambios de codigo. En ese sentido, LMLauncher complementa la literatura de serving al proponer una capa de compatibilidad y decision, mas cercana a una funcion de middleware inteligente.

La comparacion practica con soluciones centradas en un solo backend sugiere que la principal ganancia de la arquitectura propuesta esta en la flexibilidad operativa. `llama.cpp` sigue siendo valioso por su accesibilidad y control local [8], mientras que Ollama aporta una API madura con funciones modernas como structured outputs [3], [4], [5]. LMLauncher no pretende reemplazar a estos motores, sino abstraerlos para que investigadores y pequenas empresas no deban redisenar su aplicacion cada vez que cambian de modelo, cuantizacion o proveedor local.

Un aspecto adicional para la evolucion del prototipo es la optimizacion especifica por hardware. En despliegues con GPU, el rendimiento no depende unicamente del tamano del modelo, sino tambien de la forma en que el backend fue compilado o configurado para la arquitectura disponible. Por ejemplo, en tarjetas NVIDIA Ampere como RTX A4000, `llama.cpp` puede compilarse con soporte CUDA y parametros de arquitectura apropiados para `sm_86`, mientras que motores como vLLM priorizan kernels optimizados, batching continuo y gestion eficiente de memoria KV para elevar el throughput en escenarios concurrentes [6], [8]. Esta diferencia sugiere que LMLauncher puede incorporar, en fases posteriores, metadatos de hardware y perfiles de ejecucion por backend para seleccionar no solo el modelo mas compatible, sino tambien la ruta mas eficiente para una combinacion concreta de GPU, cuantizacion, longitud de contexto y nivel de concurrencia.

La prueba tambien mostro que no basta con solicitar el maximo uso de GPU de forma directa. En una corrida de Ollama con `qwen3:30b`, `num_ctx=4096` y `num_gpu=999`, el motor logro cargar 49/49 capas en GPU cuando detecto ambas tarjetas; sin embargo, una corrida posterior detecto solo una GPU y fallo por falta de memoria. El perfil productivo final evito ese extremo y uso `num_gpu=41` con el modelo `qwen3.6-sara:opt`, lo que mantuvo el modelo residente en GPU y permitio pasar las pruebas de salida estructurada y concurrencia ligera. Esto refuerza la conveniencia de que LMLauncher trate la optimizacion como un problema de perfiles medidos y no como una configuracion fija.

Una limitacion actual es que el prototipo aun no implementa balanceo distribuido con metricas en tiempo real ni conectores completos para herramientas externas mediante contratos estandarizados como MCP. Otra limitacion es que `json_schema` debe probarse con instrucciones que pidan explicitamente JSON puro: una prueba exploratoria con instruccion menos restrictiva respondio HTTP 200, pero no produjo JSON parseable. Por ello, la evidencia presentada debe interpretarse como validacion controlada de salida estructurada, no como garantia universal ante cualquier prompt. Sin embargo, la separacion lograda en esta fase hace viable extender la solucion hacia observabilidad, politicas de reintento y validacion automatica sin rediseniar la API publica.

## 6. CONCLUSIONES

LMLauncher demuestra que es factible evolucionar un servidor local de LLM hacia una arquitectura de gateway capaz de desacoplar aplicaciones cliente de motores de inferencia heterogeneos. La incorporacion de un catalogo de modelos, un resolvedor por capacidades, parametros de runtime por ruta y una interfaz compatible con el ecosistema OpenAI reduce el costo de integracion para usuarios no especializados en infraestructura de IA.

La contribucion mas relevante del prototipo es combinar interoperabilidad y decision operacional en una misma capa. El fallback automatico queda disponible cuando una ruta no cubre salida estructurada, mientras que el perfil productivo de SARA demuestra que una ruta optimizada puede atender `json_schema`, `json_object`, generacion larga y concurrencia ligera con servicios estables. En la validacion final, las generaciones de 256 y 512 tokens alcanzaron 37.53 y 40.26 tokens/s de pared, respectivamente.

Como trabajo futuro se propone incorporar observabilidad, colas distribuidas, balanceo entre nodos, conectores formales de herramientas, validacion automatica de JSON y una evaluacion experimental cuantitativa con metricas de latencia, throughput, tasa de fallback y costo de integracion frente a implementaciones acopladas a un solo backend. Tambien se plantea evaluar perfiles de compilacion y configuracion especificos por GPU para comparar el impacto de `llama.cpp`, Ollama y vLLM bajo cargas equivalentes.

## Agradecimientos

Se agradece el apoyo institucional y el acceso a infraestructura local para experimentacion y validacion del prototipo.

## BIBLIOGRAFIA

[1] OpenAI, "Structured Outputs," OpenAI, Aug. 6, 2024. [Online]. Available: https://openai.com/index/introducing-structured-outputs/

[2] OpenAI, "Responses API," OpenAI Platform Documentation, 2025. [Online]. Available: https://platform.openai.com/docs/api-reference/responses

[3] Ollama, "Generate a response," Ollama API Documentation, 2026. [Online]. Available: https://docs.ollama.com/api/generate

[4] Ollama, "OpenAI compatibility," Ollama Documentation, 2026. [Online]. Available: https://docs.ollama.com/openai

[5] Ollama, "Structured outputs," Ollama Blog, Dec. 6, 2024. [Online]. Available: https://ollama.com/blog/structured-outputs

[6] W. Kwon et al., "Efficient Memory Management for Large Language Model Serving with PagedAttention," in Proc. ACM SIGOPS 29th Symp. Operating Systems Principles, 2023.

[7] SGLang Team, "SGLang: Fast Serving Framework for Large Language Models and Vision Language Models," 2024. [Online]. Available: https://github.com/sgl-project/sglang

[8] G. Gerganov, "llama.cpp," GitHub repository, 2023-2026. [Online]. Available: https://github.com/ggml-org/llama.cpp

[9] JSON Schema, "JSON Schema Core Specifications," 2025. [Online]. Available: https://json-schema.org/

[10] FastAPI, "FastAPI Documentation," 2026. [Online]. Available: https://fastapi.tiangolo.com/

[11] B. Roziere et al., "Code Llama: Open Foundation Models for Code," arXiv, 2023.

[12] H. Touvron et al., "Llama 3 Model Card," Meta AI, 2024. [Online]. Available: https://ai.meta.com/

[13] BentoML, "Model Inference Gateway," BentoML Documentation, 2025. [Online]. Available: https://docs.bentoml.com/
