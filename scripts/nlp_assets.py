"""Install pinned, checksum-verified CPU models. Inference only reads local files."""
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen

ENCODER = "sentence-transformers/all-MiniLM-L6-v2/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
VERIFIER = "cross-encoder/nli-deberta-v3-xsmall/resolve/a150876415327c80daeff35ca6f68f5ed8cf5c24"
ASSETS = {
    "encoder.onnx": (ENCODER, "onnx/model_qint8_arm64.onnx", "4278337fd0ff3c68bfb6291042cad8ab363e1d9fbc43dcb499fe91c871902474"),
    "tokenizer.json": (ENCODER, "tokenizer.json", "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037"),
    "verifier.onnx": (VERIFIER, "onnx/model_qint8_arm64.onnx", "ef41fe8474f6070373f97fbe8362461d55108f387723280fcdb64f8015133db2"),
    "verifier.json": (VERIFIER, "tokenizer.json", "5124ef2ead1a10a717703bc436de7f353da76d6340e4587719b42b1693707964"),
}


def digest(path):
    with path.open("rb") as stream:
        checksum = hashlib.sha256()
        for block in iter(lambda: stream.read(1 << 20), b""):
            checksum.update(block)
        return checksum.hexdigest()


def install(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for name, (repo, remote, expected) in ASSETS.items():
        dest = directory / name
        if dest.is_file() and digest(dest) == expected:
            continue
        fd, temp = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd, "wb") as out, urlopen(f"https://huggingface.co/{repo}/{remote}", timeout=90) as data:
                shutil.copyfileobj(data, out)
            if digest(Path(temp)) != expected:
                raise ValueError(f"Checksum mismatch for {name}")
            os.replace(temp, dest)
        finally:
            Path(temp).unlink(missing_ok=True)
