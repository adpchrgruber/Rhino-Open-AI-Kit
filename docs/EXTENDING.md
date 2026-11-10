# Forking and extending Rhino Open AI Kit

The kit is small on purpose, so it is easy to read and change. Everything on the Rhino side lives in
[`rhino/rhino_ai.py`](../rhino/rhino_ai.py), in this order:

| Section | What it is |
|---|---|
| settings | finds the kit folder and reads `kit.conf` |
| server | checks, starts and talks to `llama-server` (`/v1/chat/completions`) |
| `SYSTEM_PROMPT` | the instructions and the helper list the model sees |
| `TOOLS` | the JSON schema of the tools the model may call |
| `AIHelpers` | the `ai` helper library, available as `ai` in every run |
| `tool_*` functions | what each tool does in Rhino |
| `Agent` | the loop: send messages, run tool calls, feed results back |
| `ChatForm` | the Eto chat window |

## Add a helper

Helpers matter most: a small model that can call `ai.stair(...)` does far better than one that has to
compute a stair from scratch.

1. Add a method to `AIHelpers`. Return object ids (`System.Guid`) or a list of them, so the memory
   between runs picks them up.

   ```python
   def stair(self, x, y, z, width, rise, run, steps, layer=None):
       ids = []
       for i in range(steps):
           ids.append(self.box(x + i * run, y, z + i * rise, run, width, rise, layer))
       return ids
   ```

2. Add one line to the helper list in `SYSTEM_PROMPT`, in the same style as the others:

   ```
   ai.stair(x, y, z, width, rise, run, steps) -> ids   straight stair rising along +X
   ```

3. Test it in Rhino without the model: run a small script with `_-RunPythonScript` that imports the
   file and calls `AIHelpers().stair(...)`.

## Add a tool

Tools are for things that are not "run some code": reading data the model should see, or actions that
need their own confirmation.

1. Add a schema to `TOOLS` (name, description, parameters).
2. Write a `tool_<name>()` function that runs on Rhino's UI thread and returns a string (JSON is fine).
3. Add a branch in `Agent.execute` that calls it through `self.on_ui(...)`.

Keep tool results short (they use up the context window). `tool_run_python` cuts results at 4000
characters for that reason.

## Use another model server

Any server with an OpenAI-compatible `/v1/chat/completions` endpoint and tool calling works: LM Studio,
Ollama, vLLM, a llama.cpp server on a studio workstation. Change `server_url()` (and `server_alive()` if
the server has no `/health`), and start the server yourself. If the server is on another machine,
put it behind your own network's protection: llama-server has no login.

## Add a preset

Copy a file in `presets/`, change `MODEL_REPO`, `MODEL`, `MMPROJ`, `CTX` and the comment lines at the
top (the first line is the label the setup menu shows). Mac presets must start with `mac-`, Windows
presets with `win-`, so the setup lists them.

## Keep it safe in a fork

- Keep `CONFIRM_CODE=1` as the default and keep `RISKY_PATTERNS`.
- Keep the server on `127.0.0.1` unless you know who can reach the port.
- If you pin a newer llama.cpp build, update `LLAMA_BUILD` and every SHA-256 in both setup scripts
  from the release page.
- Don't commit model files or binaries. `.gitignore` already excludes them.
- Before publishing, run `tools/privacy-check.sh` to find home paths, user names or e-mail addresses
  that slipped into files.
