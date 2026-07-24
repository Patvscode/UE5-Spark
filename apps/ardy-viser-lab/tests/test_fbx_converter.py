from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np


MODULE_PATH = Path(__file__).parents[1] / "tools" / "fbx_to_wardrobe.py"
SPEC = importlib.util.spec_from_file_location("fbx_to_wardrobe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
converter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = converter
SPEC.loader.exec_module(converter)


def _raw_skin():
    identity = np.eye(4, dtype=np.float32)
    return converter.RawSkin(
        vertices=np.zeros((2, 3), dtype=np.float32),
        faces=np.asarray([[0, 1, 1]], dtype=np.uint32),
        influence_indices=np.asarray([[0, 1], [2, -1]], dtype=np.int32),
        influence_weights=np.asarray([[0.25, 0.75], [1.0, 0.0]], dtype=np.float32),
        cluster_names=("upperarm_twist_01_l", "index_02_l", "calf_twist_02_r"),
        cluster_parents=("upperarm_l", "index_01_l", "calf_r"),
        cluster_bind_matrices=np.repeat(identity[None], 3, axis=0),
        node_parents={
            "upperarm_twist_01_l": "upperarm_l",
            "index_02_l": "index_01_l",
            "calf_twist_02_r": "calf_r",
        },
        node_matrices={},
        metadata={"mesh_name": "synthetic"},
    )


def test_core27_order_matches_ardy_definition():
    assert converter.CORE27[0] == "Hips"
    assert converter.CORE27[7:13] == (
        "RightShoulder",
        "RightArm",
        "RightForeArm",
        "RightHand",
        "RightHandEnd",
        "RightHandThumb1",
    )
    assert converter.CORE27[-4:] == (
        "LeftUpLeg",
        "LeftLeg",
        "LeftFoot",
        "LeftToeBase",
    )
    assert len(converter.CORE27) == 27


def test_extra_ue_bones_collapse_without_losing_weight():
    weights, mapping = converter.collapse_weights(_raw_skin())
    target = {name: index for index, name in enumerate(converter.CORE27)}
    assert np.allclose(weights.sum(axis=1), 1.0)
    assert weights[0, target["LeftArm"]] == 0.25
    assert weights[0, target["LeftHandEnd"]] == 0.75
    assert weights[1, target["RightLeg"]] == 1.0
    assert mapping["upperarm_twist_01_l"] == "LeftArm"
