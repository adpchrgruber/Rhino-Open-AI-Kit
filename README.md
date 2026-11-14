# Rhino Open AI Kit

An offline, open-source AI assistant for Rhino 8.

Rhino Open AI Kit is a chat window inside Rhino 8 (Mac and Windows) that talks to an open-weight language
model running on your own computer. You describe what you want ("a 13 × 13 grid of 30 mm cubes",
"offset this plan outline 200 mm inward and extrude it 3 m"), the model writes Rhino Python, you see the
code and confirm it, and it runs as a single undo step.

Everything stays on the machine. There is no account, no cloud service and no installer: one folder that
you can copy to another computer or an external SSD. Internet is needed once, to download the runtime and
a model.

> Made with generative AI assistance — see [Credits and AI disclosure](#credits-and-ai-disclosure).
> Not affiliated with Robert McNeel & Associates or with OpenAI. "Open" refers to open source and
> open-weight models.

## Contents

- [Installation](#installation)
- [Choosing a tier for your machine](#choosing-a-tier-for-your-machine)
- [Using it](#using-it)
- [How it works](#how-it-works)
- [Settings](#settings)
- [Safety](#safety)
- [Forking and extending](#forking-and-extending)
- [Not included](#not-included)
- [Credits and AI disclosure](#credits-and-ai-disclosure)
- [Licence](#licence)

## Installation

Requires Rhino 8 on macOS (Apple Silicon recommended) or Windows 10/11. No Python packages are needed:
the script uses only Rhino's built-in Python 3 and the standard library.

### Step by step

1. **Get the kit.** Click *Code › Download ZIP* on this page (or `git clone` it) and unpack it wherever
   you like, for example on an external SSD.

2. **Run the setup once** (needs internet, downloads 3 to 80 GB depending on the tier):

   - **Mac:** double-click `setup-mac.command`. If macOS refuses to open it, right-click › *Open*.
   - **Windows:** double-click `setup-win.bat`.

   The setup looks at your memory (and on Windows your NVIDIA GPU), recommends a
   [tier](#choosing-a-tier-for-your-machine), writes it to `kit.conf`, then downloads a pinned
   [llama.cpp](https://github.com/ggml-org/llama.cpp) build into `bin/` and the model into `models/`.
   Every download is checked against its SHA-256 checksum. An interrupted download resumes when you run
   the setup again.

3. **Open the chat in Rhino.** Type this command and press Enter:

   ```
   _-RunPythonScript
   ```

   and pick `rhino/rhino_ai.py` from the kit folder. The chat window opens and starts the model server
   in its own terminal window. Loading takes 10 to 60 seconds the first time.

4. **Make it a command (optional).** *Rhino Options › Aliases*, add `AI` with the macro

   ```
   ! _-RunPythonScript "/full/path/to/the/kit/rhino/rhino_ai.py"
   ```

5. **Try it.** For example: *make a 5 × 3 grid of 40 cm cubes with 10 cm gaps*.

### Manual installation

If you prefer to download by hand, the setup does nothing more than this:

| What | Where from | Put it in |
|---|---|---|
| Runtime, Mac | `llama-b12255-bin-macos-arm64.tar.gz` from the [llama.cpp b12255 release](https://github.com/ggml-org/llama.cpp/releases/tag/b12255) | unpack into `bin/mac/` |
| Runtime, Windows | `…-win-cuda-12.4-x64.zip` + `cudart-…-12.4-x64.zip` (NVIDIA), `…-win-vulkan-x64.zip` (AMD/Intel) or `…-win-cpu-x64.zip`, same release | unpack into `bin/win/` |
| Model | the file named in your preset, from the Hugging Face repo in `MODEL_REPO` | `models/` |
| Vision (optional) | `mmproj-F16.gguf` from the same repo, saved under the name in `MMPROJ` | `models/` |

Then copy the matching file from `presets/` over `kit.conf`.

## Choosing a tier for your machine

The model has to fit in memory next to Rhino. On Apple Silicon, memory is shared between CPU and GPU, so
the total RAM counts. On Windows, what counts is the graphics card's own memory (VRAM).

| Preset | Machine | Model (all Apache-2.0) | Download | Good for |
|---|---|---|---|---|
| `mac-8gb` | Mac, 8 GB | Qwen3.5-4B Q4_K_M | 2.7 GB | single, direct steps |
| `mac-16gb` | Mac, 16 GB | Qwen3.5-9B Q4_K_M | 5.7 GB | **tested default**: grids, solids, 2D drawing, layer edits |
| `mac-32gb` | Mac, 24–36 GB | Qwen3.8-27B UD-Q4_K_M + vision | 17.4 GB | multi-step scripting, fewer API mistakes |
| `mac-64gb` | Mac, 48–64 GB | Qwen3.8-27B Q8_0 + vision, thinking on | 30 GB | near full quality, better spatial reasoning |
| `mac-128gb` | Mac, 96–128 GB | Qwen3.5-122B-A10B UD-Q4_K_XL + vision, thinking on | 78 GB | the largest tier for one machine |
| `win-cpu` | Windows, no dedicated GPU, 16 GB RAM | Qwen3.5-4B Q4_K_M | 2.7 GB | works, but slow |
| `win-gpu-8gb` | GPU with 8 GB VRAM | Qwen3.5-9B Q4_K_M | 5.7 GB | like `mac-16gb` |
| `win-gpu-12gb` | GPU with 12 GB VRAM | Qwen3.5-9B Q6_K + vision | 8.4 GB | `mac-16gb` with vision |
| `win-gpu-16gb` | GPU with 16 GB VRAM | Qwen3.8-27B UD-IQ3_XXS | 10.9 GB | a 27B model at 3 bit |
| `win-gpu-24gb` | GPU with 24 GB+ VRAM | Qwen3.8-27B UD-Q4_K_M + vision | 17.4 GB | like `mac-32gb` |

The `win-gpu-*` presets use the CUDA build for NVIDIA cards. Without an NVIDIA card the setup switches
them to the Vulkan build, which runs on AMD and Intel GPUs. Intel Macs get the `macos-x64` build on the
CPU and should use `mac-8gb` or `mac-16gb`.

**What to expect.** Only the 16 GB tier has been tested end to end in Rhino so far. The larger tiers are
the same model families at higher quality or size; their gains are taken from general experience with
these models, not from a Rhino benchmark. No open model "understands" space: they reason about
coordinates as numbers, and that improves with model size. Three things help more than you'd think:

- **Thinking** (`THINKING=1`): the model works out positions step by step before writing code. Slower,
  but noticeably better for spatial tasks.
- **Vision** (`MMPROJ=…`): the model can look at the viewport and check its own result.
- **The `ai` helpers** (below): the model calls tested functions instead of computing geometry itself.

Want a model that is not listed? Any GGUF model with tool calling that llama.cpp supports works. Set
`MODEL_REPO`, `MODEL` and `MMPROJ` in `kit.conf` and run the setup again with `keep`.

## Using it

The chat window has a text field, **Send** and **New chat**. Everything the model does is shown in the
chat:

```
YOU: create a grid of boxes, 30 mm grid, 400 x 400 mm
  > tool: get_scene_info
  > tool: run_python
  > code:
    ids = [ai.box(i*30, j*30, 0, 30, 30, 30) for i in range(13) for j in range(13)]
    print(len(ids), "boxes")
  > result: 169 boxes
AI: Created 169 boxes in a 13 × 13 grid (390 × 390 mm; 400 / 30 = 13.3, so 13 per side).

YOU: now scale every second cube by 2.5
```

- **Before code runs**, a dialog asks you to confirm it. Read the code in the chat first.
- **Each run is one undo step.** `Undo` takes back exactly what the model did.
- **Follow-ups work.** Variables such as `ids` live on for the whole chat, so "scale every second cube"
  changes the existing cubes instead of building new ones. **New chat** forgets them.
- **Language.** The model answers in the language you write in.

| The model can | Tool |
|---|---|
| read units, layers, object counts and your selection | `get_scene_info` |
| write and run Rhino Python (RhinoCommon, rhinoscriptsyntax, the `ai` helpers) | `run_python` |
| look at the active viewport (needs vision) | `capture_viewport` |

### The `ai` helpers

The model is told to prefer this small, tested library over raw RhinoCommon, because small models
often guess RhinoCommon signatures wrong. You can use it in your own scripts too.

| Group | Helpers |
|---|---|
| Solids | `box`, `sphere`, `cylinder`, `extrude`, `revolve` (lathe profiles: bottles, vases, columns), `tube` (handles, rails, legs), `boolean_union`, `boolean_difference` |
| 2D and curves | `point`, `line`, `polyline`, `rectangle` (with corner radius), `polygon`, `circle`, `arc`, `ellipse`, `curve`, `offset`, `fillet`, `join`, `divide`, `curve_union`, `curve_difference`, `curve_intersection`, `length`, `area`, `is_closed` |
| Surfaces | `planar_surface`, `loft`, `pipe` |
| Transform | `move`, `copy`, `move_to`, `rotate`, `scale` (about each object's own centre), `mirror` |
| Arrangement | `array_grid`, `array_polar`, `array_along_curve`, `align`, `distribute`, `place_on_surface`, `distance` |
| Document | `objects`, `describe`, `center`, `bbox`, `select`, `selected`, `delete`, `layer` (nested with `Parent::Child`), `material` (colour, transparency, shine), `set_layer`, `set_name` |

The full signatures are in the system prompt at the top of [`rhino/rhino_ai.py`](rhino/rhino_ai.py).

## How it works

```
 Rhino 8                                   your computer only
┌──────────────────────────────┐          ┌───────────────────────────────┐
│ rhino/rhino_ai.py            │  HTTP    │ llama-server (llama.cpp)      │
│  chat window (Eto)           │ ───────► │  listens on 127.0.0.1:8080    │
│  agent loop, tools, ai.*     │ ◄─────── │  loads models/<MODEL>.gguf    │
│  runs code as one undo step  │          │  (+ vision projector)         │
└──────────────────────────────┘          └───────────────────────────────┘
```

- **The model server** is [llama.cpp](https://github.com/ggml-org/llama.cpp)'s `llama-server`, started by
  `start-mac.command` or `start-win.bat` with the settings from `kit.conf`. It uses Metal on Apple
  Silicon and CUDA or Vulkan on Windows, and only accepts connections from the same computer.
- **The Rhino side** is one Python 3 file. It speaks the OpenAI-compatible chat API that llama-server
  offers (the only sense in which "OpenAI" appears here), with tool calling. The model gets up to 8 rounds
  of tool calls per message.
- **Memory between runs.** Code runs in one namespace per chat. After each run the model is told which
  object-id variables exist, so it edits them instead of rebuilding.
- **Repeat guard.** Code that already failed is refused, and the model is pointed at the `ai` helpers.
- **Portable.** Paths are relative to the kit folder; `kit.conf` is found next to the script.

```
rhino-open-ai-kit/
├── kit.conf               your settings (a copy of one preset)
├── presets/               one .conf per machine tier
├── setup-mac.command      one-time download and checksum check (Mac)
├── setup-win.bat          same for Windows (runs tools/setup-win.ps1)
├── start-mac.command      starts the model server (the chat does this for you)
├── start-win.bat
├── rhino/rhino_ai.py      chat window, agent and ai helpers
├── bin/mac, bin/win       llama.cpp runtime (downloaded, not in git)
├── models/                GGUF model files (downloaded, not in git)
└── tools/                 setup and maintenance scripts
```

## Settings

Everything is in `kit.conf` (`KEY=VALUE`, no spaces around `=`). Restart the model server after a change
(close its terminal window; the chat starts it again).

| Key | Meaning |
|---|---|
| `MODEL_REPO` | Hugging Face repo the setup downloads from |
| `MODEL`, `MODEL_PARTS` | model file in `models/`; for split models the first part and the number of parts |
| `MMPROJ`, `MMPROJ_FILE` | vision projector name in `models/` (empty = off) and its name in the repo |
| `CTX` | context window in tokens. Lower it (8192) if memory runs out |
| `NGL` | layers on the GPU: `99` = all, `0` = CPU only, in between for a GPU that is a bit too small |
| `BACKEND` | llama.cpp build the setup downloads: `mac-arm64`, `mac-x64`, `win-cuda`, `win-vulkan`, `win-cpu` |
| `PORT` | local port of the model server |
| `THINKING` | `1` = reason before answering (better, slower) |
| `CONFIRM_CODE` | `1` = ask before running generated code. **Keep it on** |
| `TEMPERATURE` | sampling temperature, 0.2–0.7 is sensible for code |

## Safety

Read [SECURITY.md](SECURITY.md) before you use the kit on files you didn't make. In short:

- **The model writes code that runs with your rights.** Rhino's Python can read and write files and start
  programs. That's why every run is shown and confirmed by default (`CONFIRM_CODE=1`). Code that reaches
  files, the network or other programs is *always* confirmed, with a warning, even if you turn
  confirmation off.
- **Models make mistakes and can be misled.** Text inside a model (object names, layer names, notes) is
  read by the AI and could try to steer it. Check code before you confirm it, especially in files from
  others. Save before large operations.
- **Nothing leaves your computer.** The server listens only on `127.0.0.1`. The kit sends no telemetry.
  The only network access is the one-time setup download from GitHub and Hugging Face.
- **Downloads are verified.** The llama.cpp build is pinned and checked against its published SHA-256;
  model files are checked against the SHA-256 that Hugging Face publishes for them.
- **No binaries in this repository.** Neither the runtime nor any model is committed here.

## Forking and extending

This kit is meant to be forked. It is deliberately small: one Python file on the Rhino side, plain shell
scripts and text config. See [docs/EXTENDING.md](docs/EXTENDING.md) for the details. Directions that fit
well:

- **New helpers.** Add a method to `AIHelpers` in `rhino/rhino_ai.py` and one line to the helper list in
  `SYSTEM_PROMPT`. This is the most effective way to make a small model better at a task.
- **New tools.** Add an entry to `TOOLS` and a branch in `Agent.execute` (for example
  `get_layer_tree`, `export_view`, `read_user_text`).
- **Domain prompts.** Fork the system prompt for one discipline: façade studies, furniture joinery,
  timber framing, landscape grading. Keep the rules about `ai` helpers and memory.
- **Another runtime.** Anything with an OpenAI-compatible `/v1/chat/completions` endpoint and tool
  calling works: llama.cpp, LM Studio, Ollama, vLLM on a studio server. Change `server_url` and skip the
  start scripts.
- **Grasshopper.** A GhPython component can import the same helpers and call the same server.
- **A presets file for your studio.** Pin the models your office has tested and ship them as
  `presets/studio-*.conf`.

If you publish a fork, keep the licence notices, and please keep the code confirmation on by default.

## Not included

- No model or runtime binaries. The setup downloads them.
- No cloud models or API keys. If you want them, that is a fork (see above).
- No image-to-3D. Open models such as Hunyuan3D or TRELLIS produce meshes, not NURBS; they would be a
  separate tool.
- No Linux build of Rhino exists, so there is no Linux launcher.
- No sandbox. Confirmation is the safety mechanism; see [SECURITY.md](SECURITY.md).

## Credits and AI disclosure

Rhino Open AI Kit is published by the Rhino Open AI Kit contributors.

**Use of generative AI.** The kit was developed in conversation with *Claude* (Anthropic), working as a
coding agent in *Claude Code*, in November 2026. The AI researched the runtimes and models, wrote the
source code (the chat window, agent loop and tools, the `ai` helper library, the start and setup
scripts and the presets), tested the core helpers in Rhino 8 on macOS, and drafted this README and
SECURITY.md. People set the brief (offline, portable, open source, usable in an architecture and
design practice), tested it in Rhino, made the design decisions and reviewed the results.

**Citing the AI tools.** APA 7:

> Anthropic. (2026). *Claude* [Large language model]. https://www.anthropic.com/claude
>
> Anthropic. (2026). *Claude Code* [Computer software]. https://claude.com/claude-code

**Citing Rhino Open AI Kit.** See [`CITATION.cff`](CITATION.cff), or *Cite this repository* on the GitHub
page.

**Software and models.**

- [Rhinoceros 8](https://www.rhino3d.com/) and
  [RhinoCommon](https://developer.rhino3d.com/api/rhinocommon/) by Robert McNeel & Associates.
- [llama.cpp](https://github.com/ggml-org/llama.cpp) by Georgi Gerganov and contributors, MIT licence.
- [Qwen3.5 and Qwen3.8](https://huggingface.co/Qwen) by the Qwen team, Alibaba Cloud, Apache-2.0.
  GGUF conversions by [Unsloth](https://huggingface.co/unsloth), Apache-2.0.
- [Eto.Forms](https://github.com/picoe/Eto), the UI framework Rhino ships with.

## Licence

MIT, see [LICENSE](LICENSE). The models you download have their own licence (Apache-2.0 for all presets);
llama.cpp is MIT.
