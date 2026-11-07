"""A real, dependency-free logistic-regression training run for ClawVision."""

from __future__ import annotations

import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))
import clawvision  # noqa: E402


SEED = 2026
EPOCHS = 30
LEARNING_RATE = 0.12
random.seed(SEED)


def dataset(size: int):
    rows = []
    for index in range(size):
        label = index % 2
        center = -1.15 if label == 0 else 1.15
        rows.append((random.gauss(center, 0.85), random.gauss(center * 0.72, 0.95), label))
    random.shuffle(rows)
    return rows


def sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-max(-20, min(20, value))))


def evaluate(rows, weights):
    loss = 0.0
    correct = 0
    predictions = []
    for x1, x2, label in rows:
        probability = sigmoid(weights[0] * x1 + weights[1] * x2 + weights[2])
        loss -= label * math.log(probability + 1e-8) + (1 - label) * math.log(1 - probability + 1e-8)
        predicted = int(probability >= 0.5)
        correct += predicted == label
        predictions.append((label, predicted, probability, x1, x2))
    return loss / len(rows), correct / len(rows), predictions


train_rows = dataset(520)
validation_rows = dataset(180)
weights = [0.0, 0.0, 0.0]

with clawvision.start_run(
    "synthetic-logistic-regression",
    name="python-logreg-demo",
    params={"learningRate": LEARNING_RATE, "batchSize": len(train_rows), "dropout": 0, "optimizer": "SGD", "epochs": EPOCHS, "seed": SEED},
) as run:
    run.log_event("Python SDK 已连接 · 开始真实梯度下降")
    for epoch in range(1, EPOCHS + 1):
        gradients = [0.0, 0.0, 0.0]
        for x1, x2, label in train_rows:
            error = sigmoid(weights[0] * x1 + weights[1] * x2 + weights[2]) - label
            gradients[0] += error * x1
            gradients[1] += error * x2
            gradients[2] += error
        for index in range(3):
            weights[index] -= LEARNING_RATE * gradients[index] / len(train_rows)
        train_loss, _, _ = evaluate(train_rows, weights)
        val_loss, accuracy, predictions = evaluate(validation_rows, weights)
        run.log_metrics(
            epoch,
            train_loss=train_loss,
            val_loss=val_loss,
            accuracy=accuracy,
            learningRate=LEARNING_RATE * (1 - epoch / (EPOCHS * 1.4)),
            gpu=0,
        )
        if epoch % 5 == 0:
            run.log_event(f"epoch {epoch} · val_accuracy {accuracy:.1%}")
        time.sleep(0.08)

    matrix = [[0, 0], [0, 0]]
    samples = []
    embedding = []
    for index, (actual, predicted, probability, x1, x2) in enumerate(predictions):
        matrix[actual][predicted] += 1
        embedding.append({"x": x1, "y": x2, "z": probability * 2 - 1, "cluster": actual, "correct": actual == predicted})
        if index < 12:
            samples.append({"id": index, "actual": actual, "predicted": predicted, "confidence": round(max(probability, 1 - probability) * 100)})
    run.log_artifact("confusion-matrix", matrix, "confusion-matrix", EPOCHS)
    run.log_artifact("sample-predictions", samples, "sample-predictions", EPOCHS)
    run.log_artifact("embedding-3d", embedding, "embedding-3d", EPOCHS)
    run.log_artifact("model-weights", {"weights": weights}, "checkpoint-metadata", EPOCHS)
    run.log_event("模型权重与诊断产物已保存")

print("Demo run completed. Open http://127.0.0.1:4173")
