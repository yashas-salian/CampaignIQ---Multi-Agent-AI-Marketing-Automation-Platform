"""Turn the persona figures into rotatable 3D models (frontend/public/personas/models/<figure>.glb).

Uses Microsoft's TRELLIS image-to-3D demo on Hugging Face (free; GPU time is
rationed per day) on the 2D figures made by render_personas.py, so each model
matches its picture. The demo cuts the figure out of its background first.
Put HF_TOKEN (a free Hugging Face account token, read access) in the repo's
.env for a usable daily allowance; it is never printed. Needs
`pip install "gradio_client<2"` in the venv.

    python frontend/scripts/make_persona_models.py teacher-female   # one
    python frontend/scripts/make_persona_models.py                  # every missing model
"""
import os
import shutil
import sys
import time
from pathlib import Path

from gradio_client import Client, handle_file

ROOT = Path(__file__).resolve().parents[2]
FIGURES = ROOT / "frontend" / "public" / "personas"
OUT = FIGURES / "models"
SPACE = "trellis-community/TRELLIS"


def hf_token() -> str | None:
    token = os.environ.get("HF_TOKEN")
    if not token and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("HF_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    return token or None


def make(client: Client, figure: str) -> None:
    started = time.time()
    cutout = client.predict(handle_file(str(FIGURES / f"{figure}.webp")), api_name="/preprocess_image")
    result = client.predict(
        image=handle_file(cutout),
        multiimages=[],
        seed=0,  # fixed, so a re-run reproduces the same model
        ss_guidance_strength=7.5,
        ss_sampling_steps=12,
        slat_guidance_strength=3.0,
        slat_sampling_steps=12,
        multiimage_algo="stochastic",
        mesh_simplify=0.95,  # keep ~5% of faces: light enough for the web
        texture_size=1024,
        api_name="/generate_and_extract_glb",
    )
    glb = Path(result[2] or result[1])  # (preview video, model, download)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{figure}.glb"
    shutil.copyfile(glb, target)
    print(f"ok {figure} ({target.stat().st_size // 1024} KB, {time.time() - started:.0f}s)", flush=True)


if __name__ == "__main__":
    token = hf_token()
    if not token:
        print("No HF_TOKEN in .env: using the small anonymous GPU allowance.", flush=True)
    client = Client(SPACE, hf_token=token, verbose=False)  # gradio_client<2 names it hf_token
    try:
        client.predict(api_name="/start_session")
    except Exception:  # older builds of the demo have no session step
        pass
    figures = sorted(p.stem for p in FIGURES.glob("*-*.webp"))
    # The free GPU allowance makes ~6 models a day: do the roles personas get
    # most often first, so most campaigns show 3D soonest.
    priority = ["general", "professional", "entrepreneur", "student", "parent", "developer", "designer", "creator",
                "teacher", "doctor", "nurse", "finance", "retiree", "traveler", "athlete", "chef", "gamer",
                "tradesperson", "scientist", "farmer"]
    rank = {role: i for i, role in enumerate(priority)}
    figures.sort(key=lambda f: (rank.get(f.rsplit("-", 1)[0], len(priority)), f))
    wanted = sys.argv[1:] or [f for f in figures if not (OUT / f"{f}.glb").exists()]
    for name in wanted:
        if name not in figures:
            print(f"skip {name}: no such figure", flush=True)
            continue
        try:
            make(client, name)
        except Exception as exc:  # GPU quota or a busy demo: report and keep going
            message = str(exc).splitlines()[0][:240]
            print(f"FAILED {name}: {message}", flush=True)
            if "quota" in message.lower():
                print("Daily GPU allowance used up; run again later.", flush=True)
                break
