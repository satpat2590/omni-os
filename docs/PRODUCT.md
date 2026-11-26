# Omni OS product requirements · Sprint 1

Omni OS runs personal growth automations on hardware the user controls. Atma supplies the first domain and the first evidence that an automation matters to its owner. A successful first session starts with an activity the person wants to try and ends with a tree they can recognize and correct.

| User | Job | Sprint acceptance |
|---|---|---|
| New local owner | Start from a clone and keep personal data local | One installer checks prerequisites, creates a private database cluster, migrates both databases and launches Atma. Restart preserves tasks. |
| Person trying an activity | Capture a task without inventing a taxonomy or assigning points | A title alone yields an owned task, a category and an attached tag. The stored decision identifies its source. Completion calculates points. |
| Person organizing their tree | Move a branch as their understanding changes | Reparenting preserves IDs, descendants and task links. A cycle or cross-category move is rejected. Refresh shows the revised ancestry. |
| Domain developer | Run a repeatable automation and change model providers | A registered Python script can use the shared provider API. A mindmap refresh writes a run ledger row. A provider failure falls back to offline classification. |
| Operator | Test a common base before adopting it | Test Atma and core together under Omni Dev. Promote a reviewed public-base commit separately from private instance configuration. |

## Platform boundary

Core owns the job registry, runner and run ledger. Atma owns tasks, tags, evidence and points. They ship in one repository and version together. The runner invokes the domain's command and receives an exit status. Atma owns the interpretation of its data. A future paid Atma suite needs a separate product and licensing decision.

The installed registry uses the script harness. A user-authored Omni agent can be a registered command that calls a provider and uses the Atma API with an explicit token. The provider accepts messages and returns text. Atma validates suggestions before writing. Scripts that call paid APIs need their own usage accounting because the existing script adapter books zero cost. This sprint enables no paid jobs by default.

Existing optional Hermes, OpenCode and Pi adapters remain for earlier instances. External development tools work on branches using ordinary Git and tests. An external runtime can submit work through the same API contract under the owner's chosen scope. A managed fleet, credential distribution, automatic deployments and model training are future work.

## Governance version 1

The installer enables governed creation for both task-create routes. A title-only request also selects it on older installs. An explicit category on a legacy install retains its previous behavior. With no configured model, keyword matches select a seed label. Unrecognized titles land in Exploration under the supplied category or Mental. This provisional choice is a prompt for user review.

An enabled provider receives the title, description, optional category and up to 300 catalog rows. It proposes a category and up to three parent-first labels. Atma rejects malformed paths and scores sibling names within the same category and parent using case-folded word normalization and a sequence similarity cutoff of 0.92. A single-label suggestion follows a unique exact match anywhere within the root, including after a move. Exact ties prefer the oldest ID. Different branches can contain the same name. Semantic synonyms depend on the provider or human judgment. The task, decision snapshot and tag links commit together. Provider selection and similarity cutoff need calibration with real tasks.

A move updates one parent ID after checking its ancestry. Postgres serializes governed moves and tag creation. Ancestor checks have cost proportional to tree depth. Descendants and completions retain their IDs. The next graph refresh rolls past points up the current ancestry. Historical reports by former ancestry would require a separate history model.

Default priority is 3. Base points are ten times priority. Daily recurrence multiplies this by 0.3, quality adjusts by up to 20 percent, and late completion reverses the sign. The score reflects the current policy and needs user validation. Known one-off duplicate awards and the 28-day expectation for new tasks limit score interpretation.

## First human test and release decision

In Omni Dev, create three activities in your own words, including an unfamiliar one. Record the expected branch before inspecting the result. Complete one activity, refresh the map, move a tag and describe whether the result suggests another activity worth trying. Record time to first task, accepted classifications out of three, any surprise about points, and one next action. Capture observations and severity in the company sprint board. Prioritize the backlog after the session.

Engineering acceptance uses a fresh macOS clone, isolated Postgres, API and renderer tests, and the local provider contract test. Human acceptance requires a recorded session. Provider quality, model costs, multi-user exposure, and installation on Linux remain unverified.
