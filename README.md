# Omni OS

Omni runs a personal growth platform on your Mac. Atma is its built-in product. A fresh installation has one domain, Atma, and an empty automation registry. Your tasks, tags, completions and settings belong to your local installation.

## Install on macOS

Use a regular Mac account with Xcode Command Line Tools, uv and PostgreSQL 16 or later. Keep the checkout where you install it. Run `./install.sh check` for prerequisites and `./install.sh` to install. The installer builds two native applications in your user Applications folder and provisions a private PostgreSQL cluster inside the checkout's ignored `.omni-local` directory. The apps use that installation's code and data. After moving a checkout, rerun the installer from its new location.

Open **Atma** from Finder or Spotlight. Enter the title of an activity and choose **Add task**. Use the circle to complete it or its menu to rename or archive it. History retains finished and archived tasks. World Tree groups activities under their categories and tags with earned points.

Open **Omni** to start or stop the platform, choose whether opening Atma starts it, and configure domains and automations. An automation runs an executable you choose under your own account. Use **Run** to start it on demand. Its status comes from the Omni run ledger. Closing a window leaves the platform available. **Stop Omni** shuts down this installation's database.

## Atma classification

Omni → Atma classification controls the daily pass. It defaults to the offline catalog, which recognizes complete activity titles. Other wording and tasks with descriptions wait for contextual classification. Select **Catalog and model**, enter an OpenAI-compatible base URL, model ID and optional API key, then save. OpenRouter uses `https://openrouter.ai/api/v1`. A local server can use a loopback URL such as `http://127.0.0.1:8080/v1`. Remote endpoints require HTTPS. The key is stored in the installing account’s private, mode-600 classifier settings file outside version control. Changing the endpoint clears the old key unless you enter a replacement.

Use **Classify now** for an immediate pass. The per-user LaunchAgent runs at 3 AM local time and checks at login. A stopped Omni database stays stopped. The report gives call, classification, pending and error counts. If the model needs clarification, Atma shows **Needs context**. Use **Edit task** to describe the intended outcome, then run the next pass. Switch back to offline mode to keep task content on this Mac.

## Development

Atma's local service code lives in `atma/api`. The two SwiftUI apps live in `mac` and share a local command interface in `scripts/desktop.py`. Routine Mac use requires no HTTP listener. The script runner and run ledger live in `core`. Environment-specific registries, agent harnesses and other domains can be added by an instance owner. See the [product requirements](docs/PRODUCT.md), [data model](docs/DATA-MODEL.md) and [base development workflow](docs/DEVELOPMENT.md).

Run `./install.sh test` after installation for the integrated suites. Install the app build again after changing Swift code. This is a locally compiled macOS alpha. A distribution license has yet to be selected.
