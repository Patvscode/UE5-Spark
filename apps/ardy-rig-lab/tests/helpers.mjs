import {
  COORDINATE_SYSTEM,
  CORE27_JOINTS,
  NEUTRAL_CORE27_POSITIONS,
  SOURCE_REVISION,
} from "../src/poseProtocol.js";

export function poseBatch(sequence = 1, frameCount = 8) {
  const identity = [0, 0, 0, 1];
  return {
    version: 2,
    sequence,
    fps: 20,
    coordinateSystem: COORDINATE_SYSTEM,
    source: {
      system: "nv-tlabs/ardy",
      revision: SOURCE_REVISION,
      skeleton: "Core27",
      jointOrder: [...CORE27_JOINTS],
      rotationSpace: "local",
      quaternionOrder: "xyzw",
      positionSpace: "global",
      contactOrder: ["left_heel", "left_toe", "right_heel", "right_toe"],
    },
    frames: Array.from({ length: frameCount }, (_, frameIndex) => {
      const positions = NEUTRAL_CORE27_POSITIONS.map((position) => [...position]);
      positions[0][2] += frameIndex * 0.002;
      return {
        time: frameIndex / 20,
        root: [...positions[0], ...identity],
        joints: CORE27_JOINTS.map(() => [...identity]),
        positions,
        contacts: [0, 0, 0, 0],
      };
    }),
  };
}

export function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}
