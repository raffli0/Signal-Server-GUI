import sys
import re

with open("Signal-Server/src/models/los.cc", "r") as f:
    content = f.read()

content = content.replace(
    "elev, y, coherent, 0.5",
    "elev, y, coherent, 0.0"
)

with open("Signal-Server/src/models/los.cc", "w") as f:
    f.write(content)

with open("gui/src/signal_gui/radio_link_window.py", "r") as f:
    content = f.read()

content = content.replace(
    "surface_roughness_m=0.5",
    "surface_roughness_m=0.0"
)

with open("gui/src/signal_gui/radio_link_window.py", "w") as f:
    f.write(content)
