from lmserv.gateway.catalog import GatewayCatalog
from lmserv.gateway.models import ModelCapabilities, ModelRoute
from lmserv.gateway.resolver import CapabilityRequirements, CapabilityResolver


def test_resolver_falls_back_to_structured_output_model():
    catalog = GatewayCatalog(
        default_model="main",
        routes=(
            ModelRoute(
                name="main",
                backend="llama_cpp",
                target="models/main.gguf",
                capabilities=ModelCapabilities(structured_output=False),
            ),
            ModelRoute(
                name="formatter",
                backend="ollama",
                target="llama3.1:8b",
                priority=50,
                capabilities=ModelCapabilities(
                    structured_output=True,
                    json_mode=True,
                    tools=True,
                ),
            ),
        ),
    )

    resolver = CapabilityResolver(catalog)
    selection = resolver.resolve(
        requested_model=None,
        requirements=CapabilityRequirements(structured_output=True),
    )

    assert selection.primary_route.name == "main"
    assert selection.selected_route.name == "formatter"
    assert selection.reason is not None
    assert "structured_output" in selection.reason
