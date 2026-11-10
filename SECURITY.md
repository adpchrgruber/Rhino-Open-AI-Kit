# Security

Rhino Open AI Kit lets a language model write Python code that runs inside Rhino. Please read this page
before you use it, and before you change its defaults.

## What the kit can do on your computer

- **Run code with your rights.** `run_python` executes the model's code in Rhino's Python 3. That
  Python can read and write any file you can, open network connections and start programs. The kit
  is *not* a sandbox.
- **Start one local program.** The chat starts `llama-server` from `bin/` through `start-mac.command`
  or `start-win.bat`, in a terminal window you can see and close.
- **Clear the macOS quarantine flag** on `bin/mac` only, because the llama.cpp binaries are not
  signed by Apple. Setup does this only after the SHA-256 checksum has matched.

## What protects you

| Measure | Where |
|---|---|
| Every code run is shown in the chat and needs your **Yes** (`CONFIRM_CODE=1`, the default) | `kit.conf`, `Agent.execute` |
| Code that mentions files, network, other programs, dynamic code or Rhino commands is **always** confirmed, with a warning, even with `CONFIRM_CODE=0` | `RISKY_PATTERNS` in `rhino/rhino_ai.py` |
| Each run is one undo step | `tool_run_python` |
| The model server listens on `127.0.0.1` only, so other machines on the network can't use it | start scripts |
| No telemetry, no accounts, no API keys; no network access after setup | whole kit |
| The llama.cpp build is pinned (`b12255`) and verified against its published SHA-256 | `setup-mac.command`, `tools/setup-win.ps1` |
| Model files are verified against the SHA-256 Hugging Face publishes for them | same |
| No executables or model weights are stored in this repository | `.gitignore` |

The pattern check is a guard against honest mistakes, not a security boundary: code can be written
to avoid it. The confirmation dialog, and you reading the code, are the real safeguard.

## Risks you should know about

- **Prompt injection.** The model reads object names, layer names and other text from your model.
  A file from someone else could contain text written to steer the AI into running harmful code.
  Be most careful with files you didn't make, and never turn confirmation off for them.
- **Wrong code.** Small models make mistakes. They may delete or change the wrong objects. Save
  before larger operations; one `Undo` reverts one run.
- **Downloaded models.** Only use GGUF files from sources you trust. GGUF is a data format and does
  not run code by itself, but the runtime that reads it is software with its own bugs. Keep
  llama.cpp reasonably up to date if you replace the pinned build.
- **Port conflicts.** If another program already uses port 8080, the chat may talk to it instead.
  Change `PORT` in `kit.conf`.

## Reporting a vulnerability

Please don't open a public issue for a security problem. Use GitHub's **private vulnerability
reporting** (*Security › Report a vulnerability* on the repository page). Describe what you found and
how to reproduce it. There is no bounty; reports are handled on a best-effort basis.
