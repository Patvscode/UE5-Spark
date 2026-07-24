"""Select the reviewed Aoi preset in the fail-closed MetaHuman builder."""

import os
import runpy


os.environ["FAY_METAHUMAN_CHARACTER"] = "Aoi"
runpy.run_path(
    os.path.join(os.path.dirname(__file__), "build_ada.py"),
    run_name="__main__",
)
