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

La integracion de aplicaciones con modelos de lenguaje de gran tamano aun presenta barreras importantes para investigadores, laboratorios y pequenas empresas que desean operar con infraestructura local o hibrida. En la practica, cada motor de inferencia expone diferencias de protocolo, capacidades y configuracion, lo que obliga a desarrollar capas de adaptacion especificas para cada herramienta cliente. Este trabajo presenta LMLauncher, una arquitectura de gateway local orientada a desacoplar a las aplicaciones consumidoras del motor de inferencia subyacente. La propuesta introduce una capa de compatibilidad tipo OpenAI, un catalogo de modelos y un resolvedor de capacidades que enruta peticiones hacia distintos backends, como `llama.cpp` y `Ollama`, segun los requisitos funcionales de la solicitud. Un caso prioritario es la conmutacion automatica cuando el modelo principal no soporta salidas estructuradas y la solicitud requiere `structured output`. El sistema redirige la inferencia a un modelo alternativo compatible sin exponer la complejidad al usuario final. La contribucion principal es una base reproducible y extensible para servir aplicaciones de investigacion y negocio con menor costo de integracion, mejor interoperabilidad y un camino mas directo hacia el escalamiento horizontal.

**PALABRAS CLAVE:** despliegue local de LLM, gateway de inferencia, interoperabilidad, salida estructurada, serveo de modelos

## ABSTRACT

Application integration with large language models still presents significant barriers for researchers, laboratories, and small businesses aiming to operate on local or hybrid infrastructure. In practice, each inference engine exposes different protocols, capabilities, and configuration requirements, forcing teams to build custom adaptation layers for every client tool. This work presents LMLauncher, a local gateway architecture designed to decouple client applications from the underlying inference engine. The proposal introduces an OpenAI-compatible interface, a model catalog, and a capability resolver that routes requests across multiple backends, such as `llama.cpp` and `Ollama`, according to the functional needs of each request. A priority use case is automatic switching when the primary model does not support structured outputs and the request requires a schema-constrained response. In that case, the system transparently redirects inference to a compatible alternative model without exposing the complexity to the end user. The main contribution is a reproducible and extensible foundation for serving research and business applications with lower integration cost, better interoperability, and a clearer path toward horizontal scaling.

**KEYWORDS:** inference gateway, interoperability, local LLM serving, structured outputs, tool integration

## 1. INTRODUCCION

El uso de modelos de lenguaje en aplicaciones cientificas, asistentes internos, plataformas de analisis y herramientas empresariales ha crecido aceleradamente; sin embargo, una parte importante de estas soluciones continua dependiendo de APIs propietarias o de adaptaciones especificas para cada motor de inferencia [1], [2]. Este escenario es especialmente problematico para investigadores y pequenas empresas, ya que el costo de integracion no reside unicamente en ejecutar un modelo, sino en mantener compatibilidad entre clientes, motores, formatos de respuesta y mecanismos de escalado [3], [4].

La hipotesis de este trabajo es que una arquitectura de gateway, basada en compatibilidad de protocolo y resolucion explicita de capacidades, puede reducir el costo de integracion y mejorar la continuidad operativa de aplicaciones que consumen LLM locales o auto hospedados. En particular, se plantea que la seleccion automatica de modelos alternativos ante solicitudes con requisitos especificos, como `structured output`, puede ocultar limitaciones del modelo principal sin afectar la experiencia del usuario final [4], [5].

El objetivo general es disenar y prototipar una base de software llamada LMLauncher que permita a diferentes aplicaciones conectarse a multiples motores LLM mediante una sola URL y una interfaz estable. Los objetivos especificos son: a) definir un catalogo de modelos y capacidades, b) implementar un resolvedor de rutas con fallback automatico, c) exponer una interfaz de compatibilidad para clientes existentes y d) documentar una ruta de evolucion hacia escalamiento horizontal y observabilidad.

## 2. REVISION DE LA LITERATURA

La literatura reciente sobre servicio de LLM se ha concentrado fuertemente en el rendimiento del motor de inferencia y en la eficiencia del uso de memoria. vLLM introdujo `PagedAttention` para mejorar el manejo de memoria KV y elevar el throughput en escenarios multiusuario [6]. En la misma linea, sistemas como SGLang han explorado optimizaciones orientadas a programacion de inferencia, batching y composicion de flujos de generacion [7]. Estas propuestas son fundamentales para el rendimiento, pero no resuelven por si mismas el problema de interoperabilidad entre aplicaciones cliente y motores heterogeneos.

En el ecosistema practico, `llama.cpp` se ha consolidado como uno de los motores locales mas accesibles para ejecutar modelos cuantizados en hardware de consumo [8]. `Ollama`, por su parte, ha simplificado la operacion de modelos locales mediante una API estable y, mas recientemente, ha incorporado soporte para salidas estructuradas y compatibilidad parcial con el ecosistema OpenAI [3], [4], [5]. Estas herramientas facilitan la ejecucion, pero trasladan a los usuarios la decision de que backend usar y como lidiar con diferencias funcionales entre ellos.

En paralelo, la adopcion de salidas estructuradas ha tomado relevancia porque una gran parte de las aplicaciones ya no solo requiere texto libre, sino respuestas validadas contra esquemas JSON, extraccion de entidades y contratos de datos para automatizacion [1], [5], [9]. Aun asi, la disponibilidad de esta capacidad depende del motor, del modelo y del protocolo expuesto. Esto justifica un enfoque de gateway con resolucion por capacidades en lugar de un simple proxy estatico.

## 3. MATERIAL Y METODOS

El trabajo se desarrolla sobre un prototipo de software en Python denominado LMLauncher. La implementacion base utiliza FastAPI como capa HTTP y se ejecuta sobre infraestructura local o de laboratorio, con posibilidad de conectarse a motores `llama.cpp` mediante procesos persistentes y a instancias de Ollama mediante HTTP. El entorno de trabajo corresponde a una arquitectura reproducible desde repositorio fuente, con configuracion por variables de entorno y un catalogo JSON de modelos.

Metodologicamente, se adopto un diseno incremental orientado por arquitectura. Primero se reviso el servidor original para identificar acoplamientos fuertes entre API y backend. Despues se introdujeron tres componentes: un catalogo de modelos con capacidades anunciadas, un resolvedor de rutas y una capa de runtimes por backend. Finalmente, se anadio una interfaz `/v1/chat/completions` compatible con clientes estilo OpenAI para reducir el costo de adopcion por parte de aplicaciones existentes.

La logica experimental se centra en solicitudes conversacionales y en peticiones con `response_format`. Para cada solicitud, LMLauncher identifica el modelo solicitado o el modelo por defecto, evalua si cubre capacidades como `structured_output`, `json_mode` o `tools` y, si no lo hace, busca una ruta alternativa compatible. El resultado de esta evaluacion se refleja en un enrutamiento transparente al backend seleccionado.

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

Tambien se implemento un catalogo de modelos que permite declarar rutas con alias, backend y capacidades. Este mecanismo habilita un comportamiento mas cercano al objetivo del proyecto: un modelo principal puede ser el preferido para conversacion general, mientras que otro modelo puede quedar reservado como fallback para tareas que requieren salida estructurada o soporte de herramientas. La logica de resolucion se realiza antes de la inferencia y evita que la limitacion funcional del modelo principal se convierta en error expuesto al usuario.

Finalmente, el prototipo deja preparado un camino explicito hacia escalamiento horizontal. Aunque esta etapa aun no incorpora un scheduler distribuido completo, la separacion entre gateway, resolvedor y runtime facilita mover la inferencia a nodos especializados, agregar balanceo por capacidad y registrar metricas de uso, latencia y fallback.

## 5. DISCUSION DE RESULTADOS

Los resultados muestran que el problema de interoperabilidad en despliegues locales de LLM no se resuelve unicamente con un motor eficiente. Trabajos como vLLM y SGLang atacan con exito el problema del rendimiento [6], [7], pero el acoplamiento entre aplicaciones y motores sigue siendo una barrera cuando el objetivo es servir multiples herramientas con minimos cambios de codigo. En ese sentido, LMLauncher complementa la literatura de serving al proponer una capa de compatibilidad y decision, mas cercana a una funcion de middleware inteligente.

La comparacion practica con soluciones centradas en un solo backend sugiere que la principal ganancia de la arquitectura propuesta esta en la flexibilidad operativa. `llama.cpp` sigue siendo valioso por su accesibilidad y control local [8], mientras que `Ollama` aporta una API madura con funciones modernas como structured outputs [3], [4], [5]. LMLauncher no pretende reemplazar a estos motores, sino abstraerlos para que investigadores y pequenas empresas no deban redisenar su aplicacion cada vez que cambian de modelo o proveedor local.

Una limitacion actual es que el prototipo aun no implementa balanceo distribuido con metricas en tiempo real ni conectores completos para herramientas externas mediante contratos estandarizados como MCP. Sin embargo, la separacion lograda en esta fase hace viable extender la solucion hacia esa direccion sin rediseniar la API publica.

## 6. CONCLUSIONES

LMLauncher demuestra que es factible evolucionar un servidor local de LLM hacia una arquitectura de gateway capaz de desacoplar aplicaciones cliente de motores de inferencia heterogeneos. La incorporacion de un catalogo de modelos, un resolvedor por capacidades y una interfaz compatible con el ecosistema OpenAI reduce el costo de integracion para usuarios no especializados en infraestructura de IA.

La contribucion mas relevante del prototipo es el fallback automatico para solicitudes con salida estructurada, lo que permite usar un modelo principal para conversacion general y un modelo secundario para tareas con restricciones formales sin que el usuario final note el cambio de backend. Esto representa una mejora directa en robustez operativa y experiencia de integracion.

Como trabajo futuro se propone incorporar observabilidad, colas distribuidas, balanceo entre nodos, conectores formales de herramientas y una evaluacion experimental cuantitativa con metricas de latencia, throughput, tasa de fallback y costo de integracion frente a implementaciones acopladas a un solo backend.

## Agradecimientos

Se agradece el apoyo institucional y el acceso a infraestructura local para experimentacion y validacion del prototipo.

## BIBLIOGRAFIA

[1] OpenAI, "Structured Outputs," OpenAI, Aug. 6, 2024. [Online]. Available: https://openai.com/index/introducing-structured-outputs/

[2] OpenAI, "Responses API," OpenAI Platform Documentation, 2025. [Online]. Available: https://platform.openai.com/docs/api-reference/responses

[3] Ollama, "API Reference - Introduction," Ollama Documentation, 2026. [Online]. Available: https://docs.ollama.com/api/introduction

[4] Ollama, "OpenAI compatibility," Ollama Documentation, 2026. [Online]. Available: https://docs.ollama.com/api/openai-compatibility

[5] Ollama, "Structured outputs," Ollama Blog, Dec. 6, 2024. [Online]. Available: https://ollama.com/blog/structured-outputs

[6] W. Kwon et al., "Efficient Memory Management for Large Language Model Serving with PagedAttention," in Proc. ACM SIGOPS 29th Symp. Operating Systems Principles, 2023.

[7] SGLang Team, "SGLang: Fast Serving Framework for Large Language Models and Vision Language Models," 2024. [Online]. Available: https://github.com/sgl-project/sglang

[8] G. Gerganov, "llama.cpp," GitHub repository, 2023-2026. [Online]. Available: https://github.com/ggml-org/llama.cpp

[9] JSON Schema, "JSON Schema Core Specifications," 2025. [Online]. Available: https://json-schema.org/

[10] FastAPI, "FastAPI Documentation," 2026. [Online]. Available: https://fastapi.tiangolo.com/

[11] B. Roziere et al., "Code Llama: Open Foundation Models for Code," arXiv, 2023.

[12] H. Touvron et al., "Llama 3 Model Card," Meta AI, 2024. [Online]. Available: https://ai.meta.com/

[13] BentoML, "Model Inference Gateway," BentoML Documentation, 2025. [Online]. Available: https://docs.bentoml.com/
