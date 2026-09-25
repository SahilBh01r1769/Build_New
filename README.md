# First Run

First Run is a desktop tool for getting an unfamiliar Python or Node web project running locally. Give it a local folder or a public HTTPS Git URL. It inspects a few common manifests, prepares a project-local setup, starts the app, and checks for an HTTP response before reporting **Running**.

It is aimed at ordinary small web projects, not arbitrary repositories. **Blocked** and **Needs input** are useful outcomes when the tool cannot safely finish a setup.

## Use it

Python 3.11 or newer, Git (for URLs), and the relevant Python or Node runtime must already be installed.

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -e .
first-run
```

Enter a folder or an HTTPS Git URL. For a URL, choose a new destination folder. Click **Set up and run**. The plan, observations, commands, and process output appear in the window. **Stop** ends the launched process. After a successful setup, select it under **Recent** and use **Start again** to skip dependency installation and reuse the detected launch route.

For Python projects, First Run creates `.venv` inside the project and installs `requirements.txt`, or installs a `pyproject.toml` project in editable mode. For Node projects, it uses `npm ci` with a lockfile or `npm install` without one. It launches common FastAPI, Flask, Django, and Streamlit root entry points, or an npm `dev`, `start`, or `serve` script. It copies `.env.example` to `.env` when needed and asks for empty values instead of inventing secrets. Treat a project's install and start scripts as code you have chosen to run locally.

The UI stays responsive during installation. A run succeeds only while its process remains alive and a local HTTP endpoint returns a response below status 500. Successful launch details are saved in `~/.config/first-run/projects.json`; they are checked against newly detected routes before reuse. Project secrets remain in the project environment, outside this repository.

## Recovery

First Run makes a short list of launch routes from files and package scripts. If the first launch fails, an optional OpenAI decision can select another untried route, identify required user input, or stop with a blocker. The model cannot supply an arbitrary shell command. There is at most one alternative launch attempt in this version.

Set `OPENAI_API_KEY` in the environment before starting First Run to enable this recovery step. `FIRST_RUN_MODEL` can override the default `gpt-5-mini`. The provider key is removed from the environment passed to Git and project commands. The failure excerpt and detected routes are sent to the model for this decision; review application logs before enabling it for projects containing sensitive output. Normal setup and verification do not need an API key.

## Current limits

- The project must have a root `requirements.txt`, common `pyproject.toml`, or `package.json`. Entry points in unusual layouts and monorepos are not selected automatically.
- npm is the supported Node package manager. A pnpm or Yarn lockfile leads to a blocker.
- A runtime, native dependency, external service, or nonempty credential missing from the machine can still require manual setup. First Run does not install system software or edit application source.
- HTTP checks use common local ports. Printed URLs on other ports need manual inspection; apps requiring a particular health route or login may also need it.
- Recovery via the model needs a separately supplied API key. The live model call has not been exercised in the development environment.
- Desktop and process lifecycle checks have run on Linux; Windows behavior still needs a local run.

Run the focused tests with `python -m unittest discover -s tests -v`.
