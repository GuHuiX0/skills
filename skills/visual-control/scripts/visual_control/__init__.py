"""visual-control: observe the screen and drive the mouse/keyboard.

Public entry points:

* ``visual_control.cli.main`` - JSON CLI used by the skill
* ``visual_control.driver``   - backend registry, extend via ``backends/``
"""

from .driver import SCHEMA_VERSION, DriverError, load  # noqa: F401

__all__ = ["SCHEMA_VERSION", "DriverError", "load"]
__version__ = "1.0.0"
