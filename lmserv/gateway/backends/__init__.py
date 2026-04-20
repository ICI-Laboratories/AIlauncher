__all__ = [
    "LlamaCppRuntime",
    "OllamaRuntime",
]


def __getattr__(name: str):
    if name == "LlamaCppRuntime":
        from .llama_cpp import LlamaCppRuntime

        return LlamaCppRuntime
    if name == "OllamaRuntime":
        from .ollama import OllamaRuntime

        return OllamaRuntime
    raise AttributeError(name)
