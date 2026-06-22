# Turn on cloud‑level handwriting — on your own Mac Studio (nothing leaves your network)

The app reads typed forms perfectly with no model. To also read **handwriting** at cloud‑level
accuracy, run a large open **vision model on your Mac Studio**. The app sends page images to it over
**your own machine/network only** — the privacy guard refuses any internet/cloud host.

## 1. Install the model runner + a vision model (once)
```bash
bash scripts/setup_mac_ai.sh            # installs Ollama, pulls a model sized to your RAM
# or pick a model explicitly:
bash scripts/setup_mac_ai.sh qwen2.5vl:32b
```
What to pick (Mac Studio unified memory → model):

| Studio memory | Recommended model | Handwriting quality |
|---|---|---|
| 32 GB | `qwen2.5vl:7b` or `llama3.2-vision:11b` | good on hand‑printing |
| 64 GB | `qwen2.5vl:32b` | very good |
| 128 GB+ | `qwen2.5vl:72b` | closest to cloud |

The model file (a few–tens of GB) downloads once, then runs fully offline.

## 2. Point the app at it
Add to **`settings.json`** (next to the app) — no terminal needed at run time:
```json
{
  "vlm_model": "qwen2.5vl:32b"
}
```
That's it if the app runs **on the Studio itself**. To run the app on **office PCs that send pages to
the Studio** (a deliberate "computer down the hall" choice — still inside your network):
```json
{
  "vlm_model": "qwen2.5vl:32b",
  "vlm_url": "http://STUDIO-LAN-IP:11434/api/generate",
  "vlm_trusted_host": "STUDIO-LAN-IP"
}
```
`vlm_trusted_host` is required for any non‑loopback host — it's the one explicit address the guard
will allow. Every other host (the internet, the cloud) is hard‑refused.

## 3. Confirm it's live
Open the app — the header shows **“Handwriting model ✓”** when the model is reachable. Or check
`/api/vlm-test`, which reports the host, model, and the installed model list (loopback/trusted‑host
probe only — never a remote call).

## How it's used
The reader only escalates to the model for pages the form parsers + OCR couldn't read confidently —
so it's spent where it matters (messy scans, hand‑printed fields). Anything the model still isn't sure
of falls through to the human‑review queue. No internet at any step.
