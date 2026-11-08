"""Train a causal temporal CNN, with explicit session-separated evaluation."""
import argparse
import json
from pathlib import Path
import random

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .dataset import build_session
from .labels import CLASSES


class PinchTCN(nn.Module):
    """511-sample receptive field; one five-class output per trailing window."""
    def __init__(self):
        super().__init__()
        self.layers = nn.ModuleList([nn.Conv1d(8 if i == 0 else 24, 24, 3, dilation=2 ** i) for i in range(8)])
        self.head = nn.Linear(24, len(CLASSES))

    def forward(self, x):
        for i, layer in enumerate(self.layers):
            residual = x if i else 0
            x = torch.relu(layer(nn.functional.pad(x, (2 * 2 ** i, 0))) + residual)
        return self.head(x[:, :, -1])


def load_sessions(paths, labels_name="camera.jsonl"):
    data = [build_session(p, labels_name) for p in paths]
    if any(not len(row[1]) for row in data):
        raise ValueError('Every session must have usable windows; inspect quality reports')
    return np.concatenate([d[0] for d in data]), np.concatenate([d[1] for d in data])


def center(x):
    # Remove per-window electrode DC offset; preserve EMG amplitude information.
    return x - np.median(x, axis=1, keepdims=True)


def metrics(truth, predicted):
    confusion = np.zeros((len(CLASSES), len(CLASSES)), dtype=int)
    np.add.at(confusion, (truth, predicted), 1)
    support = confusion.sum(1)
    recall = np.divide(confusion.diagonal(), support, out=np.zeros(len(CLASSES)), where=support > 0)
    precision = np.divide(confusion.diagonal(), confusion.sum(0), out=np.zeros(len(CLASSES)), where=confusion.sum(0) > 0)
    f1 = np.divide(2 * precision * recall, precision + recall, out=np.zeros(len(CLASSES)), where=precision + recall > 0)
    return {'accuracy': float(np.mean(truth == predicted)), 'macro_f1': float(f1.mean()),
            'recall': dict(zip(CLASSES, recall.tolist())), 'support': dict(zip(CLASSES, support.tolist())),
            'confusion_rows_true_columns_predicted': confusion.tolist()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train', nargs='+', type=Path, required=True)
    parser.add_argument('--validation', nargs='+', type=Path, required=True)
    parser.add_argument('--test', nargs='+', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=30)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--labels-name', default='camera.jsonl')
    args = parser.parse_args()
    if args.epochs < 1:
        parser.error('epochs must be positive')
    groups = [set(p.resolve() for p in paths) for paths in (args.train, args.validation, args.test)]
    if any(groups[i] & groups[j] for i, j in ((0, 1), (0, 2), (1, 2))):
        parser.error('Train/validation/test must be different recording sessions')
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(min(4, torch.get_num_threads()))
    datasets = [load_sessions(paths, args.labels_name) for paths in (args.train, args.validation, args.test)]
    for name, (_, labels) in zip(('train', 'validation', 'test'), datasets):
        if set(labels.tolist()) != set(range(len(CLASSES))):
            parser.error(f'{name} must contain all five classes; collect more valid trials')
    scale = np.maximum(center(datasets[0][0]).std(axis=(0, 1)), 1.)
    tensors = [(torch.tensor((center(x) / scale).transpose(0, 2, 1), dtype=torch.float32), torch.tensor(y)) for x, y in datasets]
    loader = DataLoader(TensorDataset(*tensors[0]), batch_size=64, shuffle=True)
    counts = np.bincount(datasets[0][1], minlength=len(CLASSES))
    loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(len(datasets[0][1]) / (len(CLASSES) * counts), dtype=torch.float32))
    model = PinchTCN()
    optimizer = torch.optim.Adam(model.parameters(), lr=.001)
    args.output.mkdir(parents=True, exist_ok=False)
    best, history = -1., []
    for epoch in range(args.epochs):
        model.train()
        for x, y in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(x), y)
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            predicted = torch.cat([model(x).argmax(1) for x in tensors[1][0].split(128)]).numpy()
        result = metrics(datasets[1][1], predicted)
        history.append({'epoch': epoch + 1, 'validation': result})
        print(f'epoch {epoch + 1}: validation macro F1={result["macro_f1"]:.3f}', flush=True)
        if result['macro_f1'] > best:
            best = result['macro_f1']
            torch.save({'state_dict': model.state_dict(), 'scale': scale.tolist(), 'classes': list(CLASSES),
                        'sample_rate': 2048, 'window_samples': 512, 'preprocessing': 'window_median_then_training_scale',
                        'architecture': 'PinchTCN-v1'}, args.output / 'model.pt')
    checkpoint = torch.load(args.output / 'model.pt', weights_only=True)
    model.load_state_dict(checkpoint['state_dict'])
    with torch.no_grad():
        predicted = torch.cat([model(x).argmax(1) for x in tensors[2][0].split(128)]).numpy()
    report = {'classes': CLASSES, 'seed': args.seed, 'history': history, 'labels_name': args.labels_name,
              'sessions': {name: [str(p.resolve()) for p in paths] for name, paths in
                           zip(('train', 'validation', 'test'), (args.train, args.validation, args.test))},
              'test': metrics(datasets[2][1], predicted),
              'limits': 'Stable webcam pseudo-labels only. Does not measure transition accuracy, event false positives, or end-to-end latency.'}
    (args.output / 'metrics.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['test'], indent=2))


if __name__ == '__main__':
    main()
