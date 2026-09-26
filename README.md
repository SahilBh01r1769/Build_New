# First Run

First Run is a desktop tool I built for the awkward first run of an unfamiliar web project. Give it a local folder or a public HTTPS Git URL. It looks for common Python or Node setup files, prepares dependencies, starts the app, and checks an HTTP route before reporting **Running**.

It is aimed at ordinary small web projects, not arbitrary repositories. **Blocked** and **Needs input** are useful outcomes when the tool cannot safely finish a setup.

![First Run recovering from two failed npm scripts before verifying the third route](docs/first-run-recovery.png)

The screenshot is from a small local three-script project. The first two scripts exit; the third serves HTTP 200. Its recovery decisions used rules, not an API key.

## Use it

Python 3.11 or newer, Git (for URLs), and the relevant Python or Node runtime must already be installed.

**Windows:** [Download the ZIP](https://github.com/SahilBh01r1769/Build_New/archive/refs/heads/main.zip), extract it where you want the project to live, and double-click `run-windows.cmd`. The first launch creates `.venv` beside the launcher and installs the desktop dependency; later launches reuse it. The Windows `py` launcher must be available. Click **Try example** then **Set up and run** for a small Flask app that needs no Node installation. After it reports **Running**, try **Open app**, **Stop**, and **Start again**.

**Try recovery** selects a second bundled Flask fixture. Its `app.py` is a plausible but wrong entry point; `main.py` contains the runnable app. First Run should observe the failed guess and try `main.py`. This fixture checks the recovery path, not broad compatibility. With a valid OpenAI API key entered locally, click **Test key** first, then **Try recovery** and **Set up and run**; the decision source tells you whether the model participated. The key is optional and should never be pasted into an issue or chat.

The launcher and its environment stay in the folder you extracted. Python and pip may still use their normal system temporary and cache folders during installation.

**macOS/Linux or manual installation:**

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
first-run
```

Enter a folder or an HTTPS Git URL. For a URL, choose a new destination folder. Click **Set up and run**. The current action, latest observation, recovery decision, and full process output appear in the window. A single nested project (for example, `apps/web/package.json`) is found automatically. If several components are found, choose the folder you want to run. When an environment value is missing, fill the named value in `.env` and click **Continue setup**. An unreachable MongoDB connection also produces **Needs input**: check the project's database URL and service, then continue. A completed installation is reused while its manifest and installed environment still match. **Stop** ends the launched process. After a successful setup, select it under **Recent** and use **Start again** to reuse the verified route.

For Python projects, First Run creates `.venv` inside the project and installs `requirements.txt`, or installs a `pyproject.toml` project in editable mode. For Node projects, it uses `npm ci` with a lockfile or `npm install` without one. It launches common FastAPI, Flask, Django, and Streamlit root entry points, or an npm `dev`, `start`, or `serve` script. If a Django app reports missing tables and unapplied migrations, First Run can apply migrations to a fresh project-local SQLite database and retry once. It leaves existing or external databases for the user to review. It copies `.env.example` to `.env` when needed and asks for empty values instead of inventing secrets. Treat a project's install and start scripts as code you have chosen to run locally.

The UI stays responsive during installation. A run succeeds only while its process remains alive and a checked local HTTP route returns a 2xx or 3xx response. A 404 or server error is not treated as proof that the app works. Successful launch details are saved in `~/.config/first-run/projects.json`; they are checked against newly detected routes and dependency manifests before installation is skipped. Project secrets remain in the project environment, outside this repository.

## Recovery

First Run makes a short list of launch routes from files and package scripts. After a failure it records the observation, chooses a valid untried route, runs it, and observes again. It stops after five launch attempts at most. A transient network error during installation can trigger one retry. For Flask, Django, and Uvicorn CLI launches, a port found occupied before startup can be replaced with a nearby free port without killing the other process. FastAPI verification also checks `/docs` and `/openapi.json` when `/` is missing; Streamlit checks its health route. Simple Python and Node minimum-version requirements lead to **Needs input** rather than a system runtime change.

An optional OpenAI decision can choose an allowed retry, request more of an already captured long process log, explain a failure, request input, or stop. That extra inspection happens once per failed route, within a six-decision limit. The program validates the selected action and route again before executing it. Without the model, rules choose among the known routes. The model cannot supply a shell command or edit source files. Failure labels cover a few recognizable cases; unfamiliar output is shown as an unclear failure.

Enter an OpenAI key in the optional masked field to enable model decisions for that run, or set `OPENAI_API_KEY` before starting First Run. **Test key** makes a small model request with a sample failure and no project files or logs; it reports whether the API response was usable. The field is not saved. `FIRST_RUN_MODEL` can override the default `gpt-5-mini`. The provider key is removed from the environment passed to Git and project commands. On a real failure, the output labels the decision **AI**, **rules**, or **fallback**. The failure excerpt, detected project facts, and allowed routes are sent to the model; if it requests more captured output, up to 5,000 additional characters can be sent. Review application logs before enabling it for projects containing sensitive output. Setup, verification, and deterministic recovery do not need an API key.

## Runs checked

These are observed outcomes, not a claim of general compatibility:

| Project | Result |
| --- | --- |
| [Mythos](https://github.com/SahilBh01r1769/indo_european_gods), Node with an npm lockfile and `serve` script | HTTP 200 on port 4173; Stop and Start again worked without reinstalling (Linux, September 26). |
| Small local FastAPI fixture with `requirements.txt` | Created `.venv`, installed dependencies, and reached HTTP 200 on port 8000 (Linux, September 26). This checks the Python path, not compatibility with a public Python repo. |
| [MDN Django Local Library](https://github.com/mdn/django-locallibrary-tutorial) | Fresh checkout initially returned HTTP 500 from missing SQLite tables; First Run applied 45 migrations to its new local database and then reached HTTP 200 (Linux, September 26). |
| A copy of Mythos with a blank `DEMO_TOKEN` added to `.env.example` | Needs input named the value and file; filling it and continuing reached HTTP 200. This was an intervention check, not a requirement of the original project. |
| Small Node project with a failing `dev` script and a working `start` script | Retried the detected `start` route and reached HTTP 200 without a model key. |
| Local three-script Node project | `dev` and `start` exited; the bounded recovery loop tried `serve` and reached HTTP 200. The desktop showed both recovery decisions (Linux, September 26). |
| Local nested Node project (`apps/web`) | Located the manifest, installed in the component folder, and reached HTTP 200 (Linux, September 26). |
| Bundled Flask example with an unrelated server on port 5000 | Started on port 5001, verified HTTP 200, then reused the saved port without reinstalling on Start again (Linux, September 26). |
| [MDN Express Local Library](https://github.com/mdn/express-locallibrary-tutorial) | Dependencies installed, then startup reported **Needs input** on an unreachable MongoDB connection (Linux, September 26). The database was not supplied, so an end-to-end launch remains unverified. |
| Bundled Flask example | HTTP 200, Open app, Stop, and Start again worked on Windows (September 26, user check). |
| Bundled Flask recovery fixture | Initial `app.py` CLI launch failed; the rules chose `main.py`, reached HTTP 200 (Linux, September 26). A live AI decision on this fixture has not been tested. |
| [FastAPI example](https://github.com/vahidrezazadeh/fastapi-example) | Blocked on an application `NameError` after setup (Linux, September 25). |

## Current limits

- Component search is limited to three nested levels. A repository with multiple runnable components asks you to select one folder; First Run does not orchestrate services together.
- npm is the supported Node package manager. A pnpm or Yarn lockfile leads to a blocker.
- A runtime, native dependency, external service, or nonempty credential missing from the machine can still require manual setup. First Run does not install system software or edit application source.
- HTTP checks use common local ports and a few framework routes. Printed URLs on other ports, apps requiring login, and unusual layouts may still need manual inspection. Alternate-port behavior was checked with Flask; Django and FastAPI variants have focused tests but no comparable real-project run yet.
- Recovery via the model needs a separately supplied API key. The live model call has not been exercised in the development environment.
- The bundled example and its process controls were checked on Windows; broader Windows project compatibility remains unverified.

The inspection code identifies a component and launch routes. The runner owns installations, processes, port checks, and HTTP verification. The agent module classifies a few failures and selects only allowed recovery actions; the runner validates and executes them. History stores completed installs and successful launch routes. The desktop displays the state and keeps full command output visible.

Run the tests with `python -m unittest discover -s tests -v`. GitHub Actions runs them with Python 3.11, Node 20, and Qt's offscreen mode. The model response tests use mocks; a real API-assisted recovery still needs a key and an observed failure on the user's machine.
