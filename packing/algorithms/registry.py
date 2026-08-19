from dataclasses import dataclass

from rest_framework import serializers


GLOBAL_PARAMETERS = {
    "allow_rotation_global": {
        "type": "boolean",
        "default": True,
        "description": "Allow rotations for box types that permit rotation.",
    },
    "respect_weight": {
        "type": "boolean",
        "default": True,
        "description": "Respect the container maximum weight when it is set.",
    },
    "respect_stacking": {
        "type": "boolean",
        "default": False,
        "description": "Require supported placements and basic load-bearing checks.",
    },
}


@dataclass(frozen=True)
class AlgorithmDefinition:
    key: str
    display_name: str
    description: str
    parameters: dict
    runner: callable

    def metadata(self):
        return {
            "key": self.key,
            "display_name": self.display_name,
            "description": self.description,
            "parameters": {**GLOBAL_PARAMETERS, **self.parameters},
        }

    def validate(self, supplied):
        supplied = supplied or {}
        schema = {**GLOBAL_PARAMETERS, **self.parameters}
        unknown = set(supplied) - set(schema)
        if unknown:
            raise serializers.ValidationError(
                {name: ["Unknown algorithm parameter."] for name in sorted(unknown)}
            )
        result = {}
        errors = {}
        for name, spec in schema.items():
            value = supplied.get(name, spec.get("default"))
            expected = spec["type"]
            if expected == "boolean" and type(value) is not bool:
                errors[name] = ["Must be a boolean."]
            elif expected == "integer" and (
                type(value) is not int
                or value < spec.get("minimum", value)
                or value > spec.get("maximum", value)
            ):
                errors[name] = [
                    f"Must be an integer between {spec.get('minimum')} and {spec.get('maximum')}."
                ]
            else:
                result[name] = value
        if errors:
            raise serializers.ValidationError(errors)
        return result


class AlgorithmRegistry:
    def __init__(self):
        self._algorithms = {}

    def register(self, *, key, display_name, description, parameters=None):
        def decorator(runner):
            if key in self._algorithms:
                raise RuntimeError(f"Algorithm key already registered: {key}")
            self._algorithms[key] = AlgorithmDefinition(
                key=key,
                display_name=display_name,
                description=description,
                parameters=parameters or {},
                runner=runner,
            )
            return runner

        return decorator

    def get(self, key):
        try:
            return self._algorithms[key]
        except KeyError as exc:
            raise serializers.ValidationError(
                {"algorithm": ["Unknown algorithm key."]}
            ) from exc

    def metadata(self):
        return [self._algorithms[key].metadata() for key in sorted(self._algorithms)]


registry = AlgorithmRegistry()
