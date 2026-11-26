"""Optional semantic metadata layer.

Maps *discovered* paths to coarse roles (clock, reset, data, control, handshake)
using generic naming conventions.  It never reads source, it only annotates what
the simulator already reported, and it is entirely optional: switch it off and
the optimizer behaves exactly the same, just with less-informed target ordering.
"""

from aiduvo.semantics.layer import SemanticLayer, SemanticRole

__all__ = ["SemanticLayer", "SemanticRole"]
