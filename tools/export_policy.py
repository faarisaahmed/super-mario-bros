"""Export the trained PPO actor to ai/policy.json for the browser build.

torch has no WebAssembly build, so the web version cannot call
`PPO.load(...).predict(...)`. The actor is only 16-64-64-6 though, so we lift
the weights out here and `mario_ai.Policy` replays the forward pass in plain
Python. Re-run this after any training run:

    python3 tools/export_policy.py

It refuses to write a file whose actions disagree with torch's, so a silent
architecture change (a different net_arch or activation) fails loudly here
rather than showing up as a worse-looking Mario in the browser.
"""

import json
import os
import sys

import numpy as np
import torch
from stable_baselines3 import PPO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mario_ai import ACTION_SIZE, OBS_SIZE  # noqa: E402

# Same preference order watch_ai.py uses: the best evaluated checkpoint wins
# over the last one, because training is usually stopped early.
CANDIDATES = ["best_model/best_model.zip", "mario_model.zip"]
OUT = os.path.join("ai", "policy.json")

# Keys in the order they are applied. The critic (value_net) is training-time
# scaffolding and is deliberately not exported.
ACTOR_KEYS = [
    "mlp_extractor.policy_net.0",
    "mlp_extractor.policy_net.2",
    "action_net",
]


def main():
    src = next((p for p in CANDIDATES if os.path.exists(p)), None)
    if src is None:
        raise SystemExit(f"No trained model found (looked for {', '.join(CANDIDATES)})")

    model = PPO.load(src[: -len(".zip")], device="cpu")
    if not isinstance(model.policy.action_dist.__class__.__name__, str):
        raise SystemExit("unexpected policy type")

    sd = model.policy.state_dict()
    layers = []
    for key in ACTOR_KEYS:
        w = sd[f"{key}.weight"].detach().cpu().numpy().astype(np.float64)
        b = sd[f"{key}.bias"].detach().cpu().numpy().astype(np.float64)
        layers.append({"w": w.tolist(), "b": b.tolist()})

    in_dim = len(layers[0]["w"][0])
    out_dim = len(layers[-1]["b"])
    if in_dim != OBS_SIZE or out_dim != ACTION_SIZE:
        raise SystemExit(
            f"{src} is {in_dim}->{out_dim}; mario_ai expects "
            f"{OBS_SIZE}->{ACTION_SIZE}. Update mario_ai.py to match."
        )

    payload = {
        "source": src,
        "obs_size": in_dim,
        "action_size": out_dim,
        "activation": "tanh",
        "layers": layers,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f)

    verify(model)
    size_kb = os.path.getsize(OUT) / 1024
    print(f"wrote {OUT} from {src} ({size_kb:.0f} KB)")


def verify(model, samples=4000):
    """Every exported action must match torch's, or the export is wrong."""
    sys.path.insert(0, os.getcwd())
    from mario_ai import Policy

    policy = Policy.load(OUT)
    rng = np.random.default_rng(0)
    # Real observations are mostly 0/1 sensor flags with a few continuous
    # values, so test both that shape and unconstrained noise.
    obs = np.concatenate([
        rng.uniform(-1.5, 1.5, size=(samples // 2, OBS_SIZE)),
        rng.integers(0, 2, size=(samples // 2, OBS_SIZE)).astype(np.float64),
    ]).astype(np.float32)

    with torch.no_grad():
        expected, _ = model.predict(obs, deterministic=True)

    got = [policy.act([float(v) for v in row]) for row in obs]
    mismatched = [i for i, (a, b) in enumerate(zip(expected, got)) if int(a) != b]
    if mismatched:
        raise SystemExit(
            f"export disagrees with torch on {len(mismatched)}/{samples} samples "
            f"(first at index {mismatched[0]})"
        )
    print(f"verified: {samples}/{samples} actions match torch exactly")


if __name__ == "__main__":
    main()
