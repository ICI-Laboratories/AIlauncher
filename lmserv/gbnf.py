"""
A very simple JSON Schema to GBNF converter.
This is not a full implementation, but it's enough to handle the tool-use case.
"""

import json

def schema_to_gbnf(schema: dict) -> str:
    """
    Converts a JSON schema to a GBNF grammar string.
    """
    rules = {}
    _convert_schema("root", schema, rules)

    gbnf_string = ""
    for name, rule in rules.items():
        gbnf_string += f"{name} ::= {rule}\n"

    return gbnf_string

def _convert_schema(name: str, schema: dict, rules: dict):
    """
    Recursively converts a schema node to GBNF rules.
    """
    if name in rules:
        return

    schema_type = schema.get("type")

    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        rule_parts = ['"{"']

        # A simple way to handle properties, not perfect for all cases
        prop_rules = []
        for i, (prop_name, prop_schema) in enumerate(properties.items()):
            prop_rule_name = f"{name}-{prop_name}"
            _convert_schema(prop_rule_name, prop_schema, rules)

            # Create a rule for the key-value pair
            kv_rule = f'"\\"{prop_name}\\"" ":" {prop_rule_name}'
            prop_rules.append(kv_rule)

        # Join properties with commas
        rule_parts.append(" ( " + ' "," '.join(prop_rules) + ' )? ')
        rule_parts.append('"}"')

        rules[name] = "".join(rule_parts)

    elif schema_type == "string":
        if "enum" in schema:
            rules[name] = " | ".join(f'"\\"{val}\\""' for val in schema["enum"])
        else:
            # A basic string rule
            rules[name] = '"\\"" ([-a-zA-Z0-9_ ,./]*) "\\""'

    elif schema_type == "number":
        rules[name] = '("-"? ([0-9] | [1-9] [0-9]*)) ("." [0-9]+)? ([eE] [-+]? [0-9]+)?'

    elif schema_type == "boolean":
        rules[name] = '("true" | "false")'

    elif "oneOf" in schema:
        one_of_rules = []
        for i, sub_schema in enumerate(schema["oneOf"]):
            sub_rule_name = f"{name}-oneof-{i}"
            _convert_schema(sub_rule_name, sub_schema, rules)
            one_of_rules.append(sub_rule_name)
        rules[name] = " | ".join(one_of_rules)

    elif "$ref" in schema:
        # This is a simplification. A real implementation would need to resolve refs.
        ref_name = schema["$ref"].split("/")[-1]
        rules[name] = ref_name

    else:
        # Fallback for unknown types
        rules[name] = "null"

if __name__ == '__main__':
    # Example usage with a simple schema
    example_schema = {
      "type": "object",
      "properties": {
        "thought": {
          "type": "string"
        },
        "tool_call": {
          "type": "object",
          "properties": {
            "name": {
              "type": "string",
              "enum": ["get_weather"]
            },
            "arguments": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
                },
                "required": ["city"]
            }
          },
          "required": ["name", "arguments"]
        }
      },
      "required": ["thought"]
    }

    gbnf = schema_to_gbnf(example_schema)
    print(gbnf)
