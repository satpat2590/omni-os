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

At capture, Atma can immediately recognize a complete catalog activity when the title stands alone. “Practice Hiragana Alphabet” maps to Mental → Languages → Japanese → Hiragana and “Going to the Gym” maps to Physical → Movement. Extra wording or a description can change the goal. Free-form tasks enter the classification queue. An explicit category constrains both catalog and model decisions.

Omni.app owns provider settings, scheduling and the per-pass call limit. Atma supplies the taxonomy and validates the result. The offline catalog is the default. In model mode Omni sends the task title, description, allowed catalog paths and a bounded selection of existing tags to the configured OpenAI-compatible endpoint. Word overlap helps order candidate tags for the prompt. The model interprets intent, can reuse a tag by ID, select a catalog path, propose a child or abstain. An accepted selection records the model, the input snapshot and which field the model used as evidence.

The per-user job runs at 03:00 local time while Omni is running and at login if due. It revisits old automatic catalog assignments, pending tasks and edited inputs. Manually linked tasks keep their associations. Provider errors leave the task eligible for retry. An explicit abstention shows **Needs context** in Atma and waits for an edit. Choose **Edit task** to clarify the title or describe the intended outcome. The next pass reconsiders the task. **Classify now** starts a pass immediately.

A move updates one parent ID after checking its ancestry. Postgres serializes governed moves and tag creation. Ancestor checks have cost proportional to tree depth. Descendants and completions retain their IDs. The next graph refresh rolls past points up the current ancestry. Historical reports by former ancestry would require a separate history model.

Default priority is 3. Base points are ten times priority. Daily recurrence multiplies this by 0.3, quality adjusts by up to 20 percent, and late completion reverses the sign. The score reflects the current policy and needs user validation. Known one-off duplicate awards and the 28-day expectation for new tasks limit score interpretation.

## First human test and release decision

In Omni Dev, create three activities in your own words, including an unfamiliar one. Record the expected branch before inspecting the result. Complete one activity, inspect the World Tree, move a tag through the domain interface and describe whether the result suggests another activity worth trying. Record time to first task, accepted classifications out of three, any surprise about points, and one next action. Capture observations and severity in the company sprint board. Prioritize the backlog after the session.

Engineering acceptance uses a fresh macOS clone, isolated Postgres, API and renderer tests, and the local provider contract test. Human acceptance requires a recorded session. Provider quality, model costs, multi-user exposure, and installation on Linux remain unverified.
