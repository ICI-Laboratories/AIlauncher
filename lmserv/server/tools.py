import json
from typing import Any, Dict, List, Optional


class ToolManager:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.tools = self._load()

    def _load(self) -> Dict[str, Any]:
        """Loads tool definitions from a JSON file."""
        try:
            with open(self.filepath, 'r') as f:
                data = json.load(f)
                return {tool['name']: tool for tool in data.get('tools', [])}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        """Saves the current tools back to the JSON file."""
        with open(self.filepath, 'w') as f:
            json.dump({"tools": list(self.tools.values())}, f, indent=2)

    def get_all(self) -> List[Dict[str, Any]]:
        """Returns a list of all tools."""
        return list(self.tools.values())

    def get_one(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single tool by its name."""
        return self.tools.get(tool_name)

    def add(self, tool_data: Dict[str, Any]) -> Dict[str, Any]:
        """Adds a new tool to the collection."""
        tool_name = tool_data.get("name")
        if not tool_name:
            raise ValueError("Tool name is required.")
        if tool_name in self.tools:
            raise ValueError(f"Tool '{tool_name}' already exists.")

        self.tools[tool_name] = tool_data
        self._save()
        return tool_data

    def update(self, tool_name: str, tool_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Updates an existing tool."""
        if tool_name not in self.tools:
            return None

        # Ensure the name in the data matches the tool_name
        tool_data["name"] = tool_name
        self.tools[tool_name] = tool_data
        self._save()
        return tool_data

    def delete(self, tool_name: str) -> bool:
        """Deletes a tool by its name."""
        if tool_name not in self.tools:
            return False

        del self.tools[tool_name]
        self._save()
        return True
