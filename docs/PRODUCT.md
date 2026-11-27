# Omni OS product requirements · Sprint 1

Omni OS runs personal growth automations on hardware the user controls. Atma supplies the first domain and the first evidence that an automation matters to its owner. A successful first session starts with an activity the person wants to try and ends with a tree they can recognize and correct.

| User | Job | Sprint acceptance |
|---|---|---|
| New local owner | Start from a clone and keep personal data local | One installer checks prerequisites, creates a private database cluster, migrates both databases and installs Atma.app and Omni.app. Restart preserves tasks. |
| Person trying an activity | Capture a task without inventing a taxonomy or assigning points | A title alone yields an owned task, a category and an attached tag. The stored decision identifies its source. Completion calculates points. |
| Person organizing their tree | Move a branch as their understanding changes | Reparenting preserves IDs, descendants and task links. A cycle or cross-category move is rejected. Refresh shows the revised ancestry. |
| Domain developer | Run a repeatable automation and change model providers | The owner adds a domain and registers an executable in Omni.app. A manual run writes a ledger row. A provider failure falls back to offline classification. |
| Operator | Test a common base before adopting it | Test Atma and core together under Omni Dev. Promote a reviewed public-base commit separately from private instance configuration. |

## Platform boundary

Core owns the job registry, runner and run ledger. Atma owns tasks, tags, evidence and points. They ship in one repository and version together. The runner invokes the domain's command and receives an exit status. Atma owns the interpretation of its data. A future paid Atma suite needs a separate product and licensing decision.

The installed registry starts with the Atma domain, a script harness and zero jobs. Atma.app owns task capture, history and the World Tree. Omni.app owns runtime state, startup preference, domain registration and automation controls. A user-authored Omni agent can be a registered command that calls a provider and uses the Atma API with an explicit token. The provider accepts messages and returns text. Atma validates suggestions before writing. Scripts that call paid APIs need their own usage accounting because the existing script adapter books zero cost. This sprint enables no paid jobs by default.

Existing optional Hermes, OpenCode and Pi adapters remain for earlier instances. External development tools work on branches using ordinary Git and tests. An external runtime can submit work through the same API contract under the owner's chosen scope. A managed fleet, credential distribution, automatic deployments and model training are future work.

## Task classification

At capture, Atma applies the versioned four-root catalog to the task title and description. Atma follows the most specific supported branch. “Practice Hiragana Alphabet” maps to Mental → Languages → Japanese → Hiragana. “Practice Japanese” stops at Japanese and “Going to the Gym” stops at Physical → Movement. An explicit category constrains the search. Equally supported siblings below a base tag share their nearest common parent. A tie between base tags or a missing match leaves the task pending. Unclassified tasks stay visible in the task list and in a separate World Tree inbox. Only used labels become database tags.

The per-user maintenance job runs at 03:00 local time while Omni is running and at login if due. It repairs old Mental/Exploration fallback decisions and revisits pending tasks, earlier catalog revisions and edited titles or descriptions. A completed automatic decision for unchanged input incurs no repeat call. Operator-assigned and manually linked tasks retain their associations.

Omni’s classifier settings accept an OpenAI-compatible base URL, model ID and optional key. The offline catalog is the default. In model mode only unresolved tasks and a bounded selection of existing tag paths go to the configured endpoint. One request selects the root and either an existing tag ID, a catalog path, or a more specific child of that path. Invalid suggestions, service errors and ambiguous answers remain pending. Names are reconciled against siblings before insertion. Links and category update in one transaction after a stale-input check. Scheduled passes are deduplicated by local date and all passes have a configurable model-call limit. Monetary cost depends on the selected provider and model.

A move updates one parent ID after checking its ancestry. Postgres serializes governed moves and tag creation. Ancestor checks have cost proportional to tree depth. Descendants and completions retain their IDs. The next graph refresh rolls past points up the current ancestry. Historical reports by former ancestry would require a separate history model.

Default priority is 3. Base points are ten times priority. Daily recurrence multiplies this by 0.3, quality adjusts by up to 20 percent, and late completion reverses the sign. The score reflects the current policy and needs user validation. Known one-off duplicate awards and the 28-day expectation for new tasks limit score interpretation.

## First human test and release decision

In Omni Dev, create three activities in your own words, including an unfamiliar one. Record the expected branch before inspecting the result. Complete one activity, inspect the World Tree, move a tag through the domain interface and describe whether the result suggests another activity worth trying. Record time to first task, accepted classifications out of three, any surprise about points, and one next action. Capture observations and severity in the company sprint board. Prioritize the backlog after the session.

Engineering acceptance uses a fresh macOS clone, isolated Postgres, API and renderer tests, and the local provider contract test. Human acceptance requires a recorded session. Provider quality, model costs, multi-user exposure, and installation on Linux remain unverified.
