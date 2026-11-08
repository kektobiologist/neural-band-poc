"""Validation-only transfer experiment using Meta's official gesture backbone.

Requires the separately downloaded CC-BY-NC-4.0 upstream source/checkpoint.
No camera/prompt features enter the model. No test-session argument is provided.
"""
import argparse
from collections import Counter
import functools
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

import numpy as np
from scipy.signal import butter, resample_poly, sosfilt
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .dataset import build_session, read_rows, RATE
from .labels import CLASSES
from .train import PinchTCN, center, metrics


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def upstream_classes(source):
    sys.path.insert(0, str(Path(source).resolve()))
    from generic_neuromotor_interface.networks import DiscreteGesturesArchitecture, ReinhardCompression
    return DiscreteGesturesArchitecture, ReinhardCompression


def load_official(checkpoint, architecture, compression):
    # The official Lightning file also pickles its model/optimizer configuration.
    # Allow only the inspected classes; never disable weights_only.
    allowed = [architecture, compression, nn.LayerNorm, nn.ReLU, nn.Conv1d,
               nn.Linear, nn.LSTM, nn.Dropout, torch.optim.Adam, functools.partial]
    with torch.serialization.safe_globals(allowed):
        result = torch.load(checkpoint, map_location='cpu', weights_only=True)
    state = result['state_dict']
    if any(not k.startswith('network.') for k in state):
        raise ValueError('Unexpected checkpoint namespace')
    state = {k.removeprefix('network.'): v for k, v in state.items()}
    probe = architecture()
    probe.load_state_dict(state, strict=True)
    return state


def context_window(batches, end, count=128):
    """One second ending at this batch; reject gaps anywhere in the context."""
    if end < count:
        return None, 'warmup'
    rows = batches[end-count:end]
    for a, b in zip(rows, rows[1:]):
        if b['sequence'] != a['sequence'] + 1 or b.get('missing_before', 0):
            return None, 'sensor_gap'
        if abs((b['timestamp_us'] - a['timestamp_us']) / 1e6 - 16 / RATE) > .002:
            return None, 'device_timing'
        if b['host_monotonic_ns'] < a['host_monotonic_ns']:
            return None, 'host_reordering'
    host_duration = (rows[-1]['host_monotonic_ns'] - rows[0]['host_monotonic_ns']) / 1e9
    device_duration = (rows[-1]['timestamp_us'] - rows[0]['timestamp_us']) / 1e6
    if abs(host_duration - device_duration) > .08:
        return None, 'receipt_jitter'
    values = np.asarray([r['samples'] for r in rows], dtype=np.float32)
    if values.shape != (count, 16, 8) or not np.isfinite(values).all():
        raise ValueError('Invalid context samples')
    return values.reshape(count * 16, 8), None


def session_context(path, stride=4):
    short, labels, ends, quality = build_session(path)
    batches = [r for r in read_rows(path / 'band.jsonl') if r['event'] == 'emg_batch']
    lookup = {r['host_monotonic_ns'] / 1e9: i + 1 for i, r in enumerate(batches)}
    if len(lookup) != len(batches):
        raise ValueError('Ambiguous duplicate EMG receipt times')
    contexts, selected, rejected = [], [], Counter()
    # Subsample accepted endpoints identically for both models, before fitting.
    for i in range(0, len(labels), stride):
        values, reason = context_window(batches, lookup[ends[i]])
        if reason:
            rejected[reason] += 1
        else:
            contexts.append(values)
            selected.append(i)
    if not contexts:
        raise ValueError('No valid one-second contexts')
    idx = np.asarray(selected)
    quality.update(context_windows=len(idx), context_rejected=dict(rejected), endpoint_stride=stride)
    return np.stack(contexts), labels[idx], ends[idx], short[idx], quality


def preprocess(x):
    # Heuristic domain adaptation, NOT physical-voltage calibration. Filtering
    # starts at each context boundary; the target is in its final 250 ms.
    filtered = sosfilt(butter(4, 40, 'highpass', fs=RATE, output='sos'), center(x), axis=1)
    # Uses only this trailing context, never future recording samples. Polyphase
    # filtering has zero-padded boundaries; a streaming implementation must match.
    return resample_poly(filtered, 125, 128, axis=1).astype(np.float32)


class AdaptedGesture(nn.Module):
    def __init__(self, architecture, state=None):
        super().__init__()
        self.adapter = nn.Conv1d(8, 16, 1, bias=False)
        self.backbone = architecture()
        if state is not None:
            self.backbone.load_state_dict(state, strict=True)
        self.backbone.projection = nn.Linear(512, len(CLASSES))

    def forward(self, x):
        return self.backbone(self.adapter(x))[:, :, -1]

    def freeze_backbone(self, frozen):
        for name, param in self.backbone.named_parameters():
            param.requires_grad_(not frozen or name.startswith('projection.'))
        if frozen:
            self.backbone.eval()  # fixed feature extractor: disable its dropout


def predictions(model, x, device, batch_size):
    model.eval()
    with torch.no_grad():
        return torch.cat([model(b.to(device)).argmax(1).cpu() for b in x.split(batch_size)]).numpy()


def fit(name, architecture, state, tensors, scale, args, device):
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    model = AdaptedGesture(architecture, state).to(device)
    counts = np.bincount(tensors[0][1].numpy(), minlength=len(CLASSES))
    loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(len(tensors[0][1]) / (len(CLASSES)*counts),
                                                    dtype=torch.float32, device=device))
    loader = DataLoader(TensorDataset(*tensors[0]), batch_size=args.batch_size, shuffle=True,
                        generator=torch.Generator().manual_seed(args.seed))
    head = list(model.adapter.parameters()) + list(model.backbone.projection.parameters())
    trunk = [p for n,p in model.backbone.named_parameters() if not n.startswith('projection.')]
    optimizer = torch.optim.Adam([{'params': head, 'lr': .001},
                                  {'params': trunk, 'lr': .0001 if state is not None else .0003}])
    history, best, best_epoch = [], -1., 0
    start = time.monotonic()
    for epoch in range(args.epochs):
        frozen = state is not None and epoch < args.freeze_epochs
        model.train()
        model.freeze_backbone(frozen)
        total, examples = 0., 0
        for x, y in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(x.to(device)), y.to(device))
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite training loss')
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), .5)
            optimizer.step()
            total += loss.item() * len(y)
            examples += len(y)
        pred = predictions(model, tensors[1][0], device, args.batch_size)
        result = metrics(tensors[1][1].numpy(), pred)
        history.append({'epoch': epoch + 1, 'frozen_backbone': frozen,
                        'mean_batch_loss': total/examples, 'validation': result})
        print(f'{name} epoch {epoch+1}/{args.epochs}: loss={total/examples:.3f} '
              f'val F1={result["macro_f1"]:.3f} accuracy={result["accuracy"]:.3f} '
              f'elapsed={time.monotonic()-start:.0f}s', flush=True)
        if result['macro_f1'] > best:
            best, best_epoch = result['macro_f1'], epoch+1
            torch.save({'state_dict': {k:v.detach().cpu() for k,v in model.state_dict().items()},
                        'scale': scale.tolist(), 'classes': list(CLASSES), 'epoch': best_epoch,
                        'architecture': 'MetaGNI-adapter8to16-pinch5', 'context_samples': 2048,
                        'preprocessing': 'context_median_hp40_resample125over128_training_std_times32',
                        'seed': args.seed}, args.output / f'{name}.pt')
    saved = torch.load(args.output/f'{name}.pt', weights_only=True)
    model.load_state_dict(saved['state_dict'])
    val_pred = predictions(model, tensors[1][0], device, args.batch_size)
    train_pred = predictions(model, tensors[0][0], device, args.batch_size)
    np.savez_compressed(args.output/f'{name}-predictions.npz', truth=tensors[1][1].numpy(), predicted=val_pred)
    return {'best_epoch': best_epoch, 'history': history,
            'validation': metrics(tensors[1][1].numpy(), val_pred),
            'train': metrics(tensors[0][1].numpy(), train_pred), 'seconds': time.monotonic()-start}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--train', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=12)
    parser.add_argument('--freeze-epochs', type=int, default=3)
    parser.add_argument('--endpoint-stride', type=int, default=4)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--device', choices=['cpu', 'mps'], default='mps' if torch.backends.mps.is_available() else 'cpu')
    args = parser.parse_args()
    if args.train.resolve() == args.validation.resolve():
        parser.error('Training and validation must be different sessions')
    if not 0 <= args.freeze_epochs < args.epochs or min(args.endpoint_stride, args.batch_size) < 1:
        parser.error('Invalid training schedule or batch/stride')
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(4)
    architecture, compression = upstream_classes(args.source)
    state = load_official(args.checkpoint, architecture, compression)
    datasets = [session_context(p, args.endpoint_stride) for p in (args.train, args.validation)]
    if any(set(d[1]) != set(range(len(CLASSES))) for d in datasets):
        raise ValueError('Both sessions need all five target classes')
    processed = [preprocess(d[0]) for d in datasets]
    scale = np.maximum(processed[0].std(axis=(0,1)), 1.)
    tensors = [(torch.from_numpy((x / scale * 32).transpose(0,2,1).copy()), torch.from_numpy(d[1]))
               for x,d in zip(processed, datasets)]
    report = {'args': {k:str(v) if isinstance(v, Path) else v for k,v in vars(args).items()},
              'upstream_commit': subprocess.check_output(['git','-C',str(args.source),'rev-parse','HEAD'],text=True).strip(),
              'checkpoint_sha256': sha256(args.checkpoint),
              'quality': {name:d[4] for name,d in zip(('train','validation'), datasets)},
              'limits': ['Validation used for checkpoint selection, not an independent test.',
                         'Single seed and fixed small optimization budget; not proof of transfer benefit or failure.',
                         'Uncalibrated physical units and electrode mapping; RMS times 32 is a heuristic.',
                         'One-second context can span transitions; only final 250 ms target must be stable.',
                         'Endpoints subsampled from accepted windows; overlapping contexts are not independent trials.',
                         'Fresh rewear recording required before choosing a live replacement.']}
    report['input_hashes'] = {str(p/name):sha256(p/name) for p in (args.train,args.validation)
                             for name in ('session.json','camera.jsonl','band.jsonl')}
    (args.output/'source').mkdir()
    for name in ('meta_transfer.py','train.py','dataset.py','labels.py'):
        shutil.copy(Path(__file__).parent/name, args.output/'source'/name)
    for name in ('LICENSE','README.md'):
        shutil.copy(args.source/name,args.output/f'upstream-{name}')
    shutil.copy(args.source/'generic_neuromotor_interface/networks.py',args.output/'source/upstream_networks.py')
    (args.output/'environment.txt').write_text(subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True))
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Contexts:', {n: len(d[1]) for n,d in zip(('train','validation'),datasets)},flush=True)
    # Existing CNN scored on precisely these same validation endpoints.
    old = torch.load(args.baseline, weights_only=True, map_location='cpu')
    baseline = PinchTCN()
    baseline.load_state_dict(old['state_dict'])
    bx = torch.tensor((center(datasets[1][3])/np.asarray(old['scale'])).transpose(0,2,1),dtype=torch.float32)
    report['baseline_tcn'] = metrics(datasets[1][1],predictions(baseline,bx,'cpu',128))
    report['always_neutral'] = metrics(datasets[1][1],np.zeros_like(datasets[1][1]))
    np.savez_compressed(args.output/'validation-endpoints.npz',ends=datasets[1][2],truth=datasets[1][1])
    for name, weights in [('pretrained', state), ('random', None)]:
        report[name] = fit(name,architecture,weights,tensors,scale,args,args.device)
        (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({name:report[name]['validation'] for name in ('pretrained','random')},indent=2))


if __name__ == '__main__':
    main()
