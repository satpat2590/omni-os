# Omni classification

"Where does this belong in Omni?" Give it any text (a task, a note, a dictated prompt) and it
answers with a realm (a domain, or Atma itself) and, when one fits, the agent responsible for it.
It is built on Jev's calibrated, typed decisions rather than free-form text, and it never raises:
with no key, or a provider down, the result says `available=False`, and `keyword_classify()` gives a
deterministic answer from the taxonomy's keywords instead.

## Layout

```
classify/
├── omni_ontology.example.yaml   # the base taxonomy: Atma and Omni, no agents
├── ontology.py                  # loads the taxonomy (your omni_ontology.yaml, else the example)
├── jev_client.py                # the Jev client config (native, then OpenRouter)
├── schema.py                    # OmniClassification: the typed result
├── classifier.py                # OmniClassifier: questions → Jev → result
└── tests/
```

The taxonomy is configuration. Add a realm or an agent to your `omni_ontology.yaml` and the
classifier's label space grows, with no code change. Each realm has a `meaning`, a `description`,
`keywords` (a deterministic floor when Jev is unavailable) and its bound `agents`.

## Use

```python
from classify import OmniClassifier
c = OmniClassifier()
text = "a learning task: the hiragana curriculum, 20 minutes a day"
result = c.classify(text)
if not result.available:                      # no key, or Jev down: fall back to keywords
    result = c.keyword_classify(text)
result.top_realm()      # "atma"
result.realm_scores     # {"atma": 1.0, "omni": 0.0}
result.agent_scores     # {} until your ontology binds agents
```

Keys come from the environment only: `TYPESAFE_API_KEY` (native) or `OPENROUTER_API_KEY`.
`OMNI_JEV_*` variables set the provider order and timeout.

## Tests

```bash
PYTHONPATH=.:lib/src core/.venv/bin/python -m pytest -q classify/tests
```

The tests use `tests/fixture_ontology.yaml`, a sample taxonomy with several realms, and mock Jev.
One live smoke test runs only when `TYPESAFE_API_KEY` is set.
