"""Local English task retrieval and entailment, with no network or generative model."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from .taxonomy import CATALOG


# These are statements to test against the task, not words to search for in it.
OUTCOMES = {
    "Movement": "I intend to exercise.",
    "Walking": "I plan to go for a walk.",
    "Hiking": "I plan to hike a trail.",
    "Bills": "I intend to handle a payment or billing issue.",
    "Hiragana": "I want to learn the Japanese hiragana syllabary.",
    "Katakana": "I want to learn the Japanese katakana syllabary.",
    "Endurance": "I intend to do aerobic exercise.",
    "Health": "I intend to take care of my health.",
    "Nutrition": "I intend to improve the way I eat.",
    "Relationships": "I intend to spend time with or reconnect with someone close to me.",
    "Communication": "I intend to improve how I communicate.",
    "Networking": "I intend to develop professional connections.",
    "Community": "I intend to contribute to my community.",
    "Budgeting": "I intend to plan or track my spending.",
    "Saving": "I intend to save money.",
    "Taxes": "I intend to work on my taxes.",
    "Investing": "I intend to manage my investments.",
    "Learning": "I intend to learn something by studying or reading.",
    "Languages": "I intend to practice a language.",
    "Writing": "I intend to create a piece of writing.",
}


@dataclass(frozen=True)
class Candidate:
    root: str
    path: tuple
    examples: tuple
    hypothesis: str
    tag_id: int | None = None

    def actor_statement(self, example):
        if example == self.hypothesis:
            return self.hypothesis
        return f"I intend to {example.lower()}."


def candidates(tags, hint=None):
    available = {}
    for root, branches in CATALOG.items():
        if hint and root != hint:
            continue
        for path, examples in branches.items():
            outcome = OUTCOMES.get(path[-1], f"I intend to practice {path[-1]}.")
            available[root, path] = Candidate(root, path, (*examples, outcome), outcome)
    for tag in tags:
        root, path = tag["category"], tuple(tag["path"])
        if hint and root != hint:
            continue
        known = available.get((root, path))
        outcome = known.hypothesis if known else f"I intend to work on {path[-1]}."
        examples = known.examples if known else (" / ".join(path), outcome)
        available[root, path] = Candidate(root, path, examples, outcome, tag["id"])
    return list(available.values())


class Network:
    def __init__(self, directory, weights, tokenizer):
        self.tokenizer = Tokenizer.from_file(str(directory / tokenizer))
        self.tokenizer.enable_padding(pad_id=0)
        self.tokenizer.enable_truncation(max_length=256)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(directory / weights), options, providers=["CPUExecutionProvider"])

    def infer(self, texts):
        encodings = self.tokenizer.encode_batch(texts)
        fields = {"input_ids": "ids", "attention_mask": "attention_mask", "token_type_ids": "type_ids"}
        inputs = {node.name: np.asarray([getattr(e, fields[node.name]) for e in encodings], dtype=np.int64)
                  for node in self.session.get_inputs()}
        output, = self.session.run(None, inputs)
        return output, inputs["attention_mask"]


class SemanticClassifier:
    def __init__(self, directory, current="", ideal=""):
        directory = Path(directory)
        self.encoder = Network(directory, "encoder.onnx", "tokenizer.json")
        self.verifier = Network(directory, "verifier.onnx", "verifier.json")
        self.index = {}
        self.context = [text for text in (current, ideal) if text.strip()]

    def encode(self, texts):
        hidden, mask = self.encoder.infer(texts)
        pooled = (hidden * mask[:, :, None]).sum(axis=1) / mask.sum(axis=1)[:, None]
        return pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)

    def rank(self, row, options):
        texts = list(dict.fromkeys(text for item in options for text in item.examples if text not in self.index))
        for start in range(0, len(texts), 32):
            batch = texts[start:start + 32]
            self.index.update(zip(batch, self.encode(batch)))
        task = ". ".join(filter(None, [row["title"], row["description"]]))
        vectors = self.encode([task, *self.context])
        ranked = []
        for item in options:
            examples = np.stack([self.index[text] for text in item.examples])
            relevance = float((examples @ vectors[0]).max())
            affinity = float((examples @ vectors[1:].T).max()) if self.context else 0.0
            nearest = item.examples[int((examples @ vectors[0]).argmax())]
            ranked.append((item, relevance, affinity, nearest))
        return sorted(ranked, key=lambda result: result[1], reverse=True)

    def choose(self, row, ranked):
        # The profile never participates in the entailment test or minimum task similarity.
        shortlist = [r for r in ranked[:8] if r[1] >= 0.34]
        if not shortlist:
            return None
        full_text = "My task is to " + ". ".join(filter(None, [row["title"], row["description"]]))
        premises = [full_text]
        if row["description"] and row["description"].strip():
            premises.append(row["description"])
        # Leave room for the hypothesis. A truncated premise could omit a correction.
        if any(len(premise) > 4000 or self.verifier.tokenizer.encode(premise).overflowing
               or len(self.verifier.tokenizer.encode(premise).ids) > 220 for premise in premises):
            return None
        pairs = []
        for item, _, _, nearest in shortlist:
            for premise in premises:
                pairs.extend((premise, hypothesis) for hypothesis in (
                    item.hypothesis, item.actor_statement(nearest), item.actor_statement(item.examples[0]),
                ))
        logits = np.concatenate([self.verifier.infer(pairs[i:i+6])[0] for i in range(0, len(pairs), 6)])
        probabilities = np.exp(logits - logits.max(axis=1, keepdims=True))
        entailment = probabilities[:, 1] / probabilities.sum(axis=1)
        checks = entailment.reshape(len(shortlist), len(premises), 3).max(axis=2)
        supported = []
        for (item, similarity, affinity, _), evidence in zip(shortlist, checks):
            # A clarifying description can override a misleading title.
            support = float(evidence.max())
            if support >= 0.72 and evidence[-1] >= 0.35:
                score = 0.55 * similarity + 0.45 * support + 0.04 * affinity
                supported.append((score, item, support))
        supported.sort(key=lambda result: result[0], reverse=True)
        if not supported:
            return None
        score, item, support = supported[0]
        if len(supported) > 1 and score - supported[1][0] < 0.035:
            return None
        return item, round(support, 3)
