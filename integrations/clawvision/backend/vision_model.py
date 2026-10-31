"""A real, reproducible CPU RGB-feature softmax baseline; no simulated metrics."""
import hashlib
import io
import warnings
from pathlib import Path

from errors import ValidationError
from synthetic_renderer import numpy

PROVIDER = "cpu-rgb-softmax/1"

def environment():
    try:
        import PIL
    except ImportError as error:
        raise ValidationError("CPU image training requires Pillow and NumPy; install requirements-vision.txt") from error
    return {"provider": PROVIDER, "numpy": numpy().__version__, "pillow": PIL.__version__,
            "sourceDigest": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

def image_data(content):
    environment()
    from PIL import Image, ImageOps
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {"PNG", "JPEG"} or getattr(source, "n_frames", 1) != 1:
                    raise ValueError("only static PNG and JPEG images are supported")
                if source.width*source.height > 2048**2 or min(source.size) < 1:
                    raise ValueError("image exceeds 4 megapixels")
                image = ImageOps.exif_transpose(source).convert("RGB")
                pixel_hash = hashlib.sha256(str(image.size).encode()+image.tobytes()).hexdigest()
                image.thumbnail((512,512))
                buffer = io.BytesIO(); image.save(buffer, format="PNG", compress_level=6)
                return buffer.getvalue(), pixel_hash
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValidationError(f"invalid training image: {error}") from error

def features(content):
    from PIL import Image
    np = numpy()
    with Image.open(io.BytesIO(content)) as image:
        image = image.convert("RGB")
        pixels = np.asarray(image.resize((4,4)), dtype=np.float64)/255
        return np.concatenate((pixels.flatten(), pixels.mean(axis=(0,1)), pixels.std(axis=(0,1))))

def probabilities(x, model):
    np = numpy()
    normalized = (x-np.asarray(model["mean"]))/np.asarray(model["scale"])
    logits = normalized @ np.asarray(model["weights"]) + np.asarray(model["bias"])
    logits -= logits.max(axis=1, keepdims=True)
    value = np.exp(logits)
    return value/value.sum(axis=1, keepdims=True)

def initial(x, classes, seed):
    np = numpy()
    return {"provider": PROVIDER, "classes": classes, "epoch": 0, "mean": x.mean(axis=0).tolist(),
            "scale": np.maximum(x.std(axis=0), .05).tolist(),
            "weights": numpy().random.default_rng(seed).normal(0,.01,(x.shape[1],len(classes))).tolist(), "bias": [0.0]*len(classes)}

def step(x, labels, model, rate, regularization):
    np = numpy()
    normalized = (x-np.asarray(model["mean"]))/np.asarray(model["scale"])
    predicted = probabilities(x, model)
    loss = float(-np.log(np.maximum(predicted[np.arange(len(labels)),labels],1e-12)).mean())
    gradient = predicted.copy(); gradient[np.arange(len(labels)),labels] -= 1; gradient /= len(labels)
    weights = np.asarray(model["weights"])
    weights -= rate*(normalized.T @ gradient + regularization*weights)
    bias = np.asarray(model["bias"])-rate*gradient.sum(axis=0)
    return {**model, "weights": weights.tolist(), "bias": bias.tolist(), "epoch": model["epoch"]+1}, loss
