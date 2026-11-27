# Omni OS

Omni runs a personal growth platform on your Mac. Atma is its built-in product. A fresh installation has one domain, Atma, and an empty automation registry. Your tasks, tags, completions and settings belong to your local installation.

## Install on macOS

Use a regular Mac account with Xcode Command Line Tools, uv and PostgreSQL 16 or later. Keep the checkout where you install it. Run `./install.sh check` for prerequisites and `./install.sh` to install. The installer builds two native applications in your user Applications folder and provisions a private PostgreSQL cluster inside the checkout's ignored `.omni-local` directory. The apps use that installation's code and data. After moving a checkout, rerun the installer from its new location.

Open **Atma** from Finder or Spotlight. Enter the title of an activity and choose **Add task**. Use the circle to complete it or its menu to rename or archive it. History retains finished and archived tasks. World Tree groups activities under their categories and tags with earned points.

Open **Omni** to start or stop the platform, choose whether opening Atma starts it, and configure domains and automations. An automation runs an executable you choose under your own account. Use **Run** to start it on demand. Its status comes from the Omni run ledger. Closing a window leaves the platform available. **Stop Omni** shuts down this installation's database.

## Atma classification

Open **Omni → Atma classification** to choose how the daily pass handles free-form tasks. Recognized whole activity titles still work immediately in every mode.

| Mode | What happens | API cost |
|---|---|---|
| Static activities | Recognizes complete catalog activities and leaves other tasks pending. Runs without a model. | None |
| Local NLP (default) | Retrieves similar activities and checks whether the task supports a proposed tag. Uncertain tasks wait for context. | None |
| Local NLP + API | Sends unresolved tasks to the selected model after the local check. | Up to the configured calls per pass |
| API for all free-form tasks | Sends each queued free-form task to the selected model, subject to the same limit. | Depends on provider and model |

The installer downloads about 120 MB of checksum-verified English NLP model files once. Local inference then works offline. For a model-free installation use `./install.sh install --static-only`. You can download the models later in Omni.

Optional **Current situation** and **What do you want to work toward?** settings help rank close matches. These fields stay on the Mac unless you enable sharing with your chosen endpoint. Changing the endpoint clears that permission and the previous API key. Enter an OpenAI-compatible base URL, model ID and optional API key for the API modes. The key is stored in the installing account’s private, mode-600 settings file.

Choose **Classify now** for an immediate pass. The scheduled pass runs at 3 AM local time and checks at login. In Atma, **Needs context** means the classifier abstained. Choose **Edit task**, clarify the intended outcome, then run another pass.

## Development

Atma's local service code lives in `atma/api`. The two SwiftUI apps live in `mac` and share a local command interface in `scripts/desktop.py`. Routine Mac use requires no HTTP listener. The script runner and run ledger live in `core`. Environment-specific registries, agent harnesses and other domains can be added by an instance owner. See the [product requirements](docs/PRODUCT.md), [data model](docs/DATA-MODEL.md) and [base development workflow](docs/DEVELOPMENT.md). Coding agents start with [`AGENTS.md`](AGENTS.md).

Run `./install.sh test` after installation for the integrated suites. Install the app build again after changing Swift code. This is a locally compiled macOS alpha. A distribution license has yet to be selected.
