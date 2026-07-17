import pytest

from model_tools import DEFAULT_TOOL_NAMES
from toolsets import DEFAULT_TOOLSET, TOOLSETS, get_toolset


def test_only_one_toolset_exists():
    assert TOOLSETS == {"hermes-lite": DEFAULT_TOOL_NAMES}
    assert get_toolset() == DEFAULT_TOOL_NAMES
    assert DEFAULT_TOOLSET == "hermes-lite"
    with pytest.raises(ValueError, match="unknown toolset"):
        get_toolset("legacy")
