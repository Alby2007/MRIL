import pytest

from mril import ModelRegistry, ModelSpec


@pytest.fixture
def registry() -> ModelRegistry:
    return ModelRegistry(
        version="test-1",
        models=(
            ModelSpec("cheap-8b", tier="cheap", input_price=0.10, output_price=0.30),
            ModelSpec("mid-small", tier="cheap", input_price=0.20, output_price=0.60),
            ModelSpec("balanced-70b", tier="balanced", input_price=0.80,
                      output_price=2.40, cached_input_price=0.08),
            ModelSpec("frontier-x", tier="frontier", input_price=5.00,
                      output_price=25.00, cached_input_price=0.50),
            ModelSpec("restricted-lab", tier="frontier", restricted=True,
                      input_price=0.01, output_price=0.01),
        ),
    )
