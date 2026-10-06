"""Backend plugins for visual-control.

Every ``*.py`` module in this package is auto-discovered by
``visual_control.driver``.  A backend module must expose:

``BACKEND_INFO``  dict with at least ``name`` and ``capabilities``
``probe()``       -> ``(usable: bool, reason: str)``
``build()``       -> a driver object (see ``visual_control.driver.Driver``)

Add a file here to teach the skill a new transport (remote desktop, VNC,
webdriver, a mock recorder, ...) without touching the rest of the code.
"""
