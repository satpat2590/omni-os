"""Fresh trees must render before they have enough tags for a full PCA layout."""
import json
import math

import numpy as np
import pytest

import mindmap


def tree_data(tags):
    tasks = [{"id": 1, "title": "First experiment", "category": "mental", "priority": 3,
              "assigned_to": {"id": 1, "name": "Me", "type": "human"},
              "tag_ids": [tag["id"] for tag in tags]}] if tags else []
    return {}, tags, tasks, {}, {}


@pytest.mark.parametrize("fields", [0, 1, 2])
def test_fresh_tree_renders_with_sparse_embeddings(tmp_path, monkeypatch, fields):
    tags = [{"id": i + 1, "name": "Learning " + str(i), "parent": None,
             "category": "mental"} for i in range(fields)]
    monkeypatch.setattr(mindmap, "fetch_atma", lambda: tree_data(tags))
    # A one-term vocabulary provides fewer features than the two requested PCA components.
    monkeypatch.setattr(mindmap, "embed", lambda labels: np.arange(len(labels)).reshape(-1, 1))
    monkeypatch.setattr(mindmap, "OUT_DIR", tmp_path)
    monkeypatch.setattr(mindmap, "GRAPH_JSON", tmp_path / "graph.json")

    mindmap.main()

    graph = json.loads((tmp_path / "graph.json").read_text())
    rendered = [node for node in graph["nodes"] if node["type"] == "field"]
    assert len(rendered) == fields
    assert len(graph["nodes"]) == 4 + fields + (1 if fields else 0)
    assert all(math.isfinite(node[axis]) for node in graph["nodes"] for axis in ("x", "y"))


def test_identical_field_embeddings_still_render(tmp_path, monkeypatch):
    tags = [{"id": i, "name": "Learning", "parent": None, "category": "mental"}
            for i in (1, 2)]
    monkeypatch.setattr(mindmap, "fetch_atma", lambda: tree_data(tags))
    monkeypatch.setattr(mindmap, "embed", lambda labels: np.ones((len(labels), 1)))
    monkeypatch.setattr(mindmap, "OUT_DIR", tmp_path)
    monkeypatch.setattr(mindmap, "GRAPH_JSON", tmp_path / "graph.json")

    mindmap.main()

    graph = json.loads((tmp_path / "graph.json").read_text())
    assert len([n for n in graph["nodes"] if n["type"] == "field"]) == 2
    assert all(math.isfinite(node[axis]) for node in graph["nodes"] for axis in ("x", "y"))


def test_unclassified_activity_stays_out_of_mental_rollup(tmp_path,monkeypatch):
    tasks = [{"id":1,"category":"unclassified","title":"Try this","priority":3,
              "assigned_to":{"id":1,"name":"Me","type":"human"},"tag_ids":[]}]
    monkeypatch.setattr(mindmap,"fetch_atma",lambda: ({},[],tasks,{},{}))
    monkeypatch.setattr(mindmap,"OUT_DIR",tmp_path)
    monkeypatch.setattr(mindmap,"GRAPH_JSON",tmp_path/"graph.json")
    mindmap.main()
    graph=json.loads((tmp_path/"graph.json").read_text())
    nodes={n["id"]:n for n in graph["nodes"]}
    assert nodes["domain-mental"]["task_count"] == 0
    assert nodes["domain-unclassified"]["task_count"] == 1
    assert any(e["target"]=="domain-unclassified" and e["source"]=="task-1" for e in graph["edges"])
