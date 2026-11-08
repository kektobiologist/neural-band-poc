"""Select feature models on a separate validation session; never opens a test set."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

import joblib
import numpy as np
import sklearn
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from .dataset import build_session, read_rows
from .features import emg_features, causal_motion
from .labels import CLASSES
from .train import metrics


def load(session):
    x, y, ends, quality = build_session(session)
    motion, valid = causal_motion(read_rows(session / 'band.jsonl'), ends)
    frames = read_rows(session / 'camera.jsonl')
    times = np.asarray([r['host_monotonic_ns']/1e9 for r in frames])
    indices = np.searchsorted(times, ends, side='right') - 1
    trials = np.asarray([frames[i]['trial'] for i in indices])
    return x, y, ends, emg_features(x), motion, valid, trials, quality


def trial_metrics(y, predictions, trials):
    truth, guessed = [], []
    for trial in np.unique(trials):
        selected = trials == trial
        if len(np.unique(y[selected])) != 1:
            raise ValueError('Trial contains multiple accepted labels')
        truth.append(y[selected][0])
        guessed.append(np.bincount(predictions[selected], minlength=5).argmax())
    return metrics(np.asarray(truth), np.asarray(guessed))


def candidates():
    # A small fixed comparison, not an unbounded validation search.
    return [('lda', LinearDiscriminantAnalysis(solver='lsqr', shrinkage='auto', priors=np.ones(5)/5)),
            ('logistic', LogisticRegression(C=1., class_weight='balanced', max_iter=2000)),
            ('svm_c1', SVC(C=1., class_weight='balanced')),
            ('svm_c10', SVC(C=10., class_weight='balanced'))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, help='Existing TCN checkpoint for a same-window comparison')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.train.resolve() == args.validation.resolve():
        parser.error('Separate training and validation sessions are required')
    if args.output.exists():
        parser.error('Output must be a new directory')
    datasets = [load(p) for p in (args.train, args.validation)]
    for data in datasets:
        if set(data[1][data[5]]) != set(range(5)):
            parser.error('All classes need motion-valid windows in each split')
    args.output.mkdir(parents=True)
    report = {'selection': 'Highest validation window macro F1, fixed 12 candidates; test not read.',
              'classes': list(CLASSES), 'sklearn_version': sklearn.__version__, 'candidates': [],
              'motion_alignment': 'Causal host-receipt sample-and-hold; max age 100 ms; not hardware-synchronized',
              'sessions': {}, 'limits': 'Overlapping stable-hold windows, one validation session; motion may encode posture shortcuts. Fresh test required.'}
    for name, path, data in zip(('train', 'validation'), (args.train, args.validation), datasets):
        report['sessions'][name] = {'path': str(path.resolve()), 'quality': data[-1],
            'motion_valid_windows': int(data[5].sum()), 'motion_rejected_windows': int((~data[5]).sum()),
            'sha256': {f: hashlib.sha256((path/f).read_bytes()).hexdigest() for f in ('session.json','band.jsonl','camera.jsonl')}}
    best = -1.
    for modality in ('emg', 'motion', 'fused'):
        features = [d[3] if modality == 'emg' else d[4] if modality == 'motion'
                    else np.concatenate((d[3], d[4]), axis=1) for d in datasets]
        features = [f[d[5]] for f, d in zip(features, datasets)]
        labels = [d[1][d[5]] for d in datasets]
        for name, classifier in candidates():
            model = make_pipeline(StandardScaler(), classifier)
            model.fit(features[0], labels[0])
            predicted = model.predict(features[1])
            result = {'name': name, 'modality': modality, 'features': features[0].shape[1],
                      'train': metrics(labels[0], model.predict(features[0])),
                      'validation': metrics(labels[1], predicted),
                      'validation_trial_majority': trial_metrics(labels[1], predicted, datasets[1][6][datasets[1][5]])}
            report['candidates'].append(result)
            print(f'{modality}/{name}: validation macro F1={result["validation"]["macro_f1"]:.3f}, accuracy={result["validation"]["accuracy"]:.3f}', flush=True)
            if result['validation']['macro_f1'] > best:
                best = result['validation']['macro_f1']
                report['winner'] = result
                joblib.dump({'pipeline': model, 'modality': modality, 'classes': list(CLASSES),
                             'feature_version': 'robust-emg-causal-motion-v1', 'window_samples': 512,
                             'sample_rate': 2048, 'sklearn_version': sklearn.__version__}, args.output/'model.joblib')
                np.savez_compressed(args.output/'validation_predictions.npz', truth=labels[1], predicted=predicted,
                                    ends=datasets[1][2][datasets[1][5]], trials=datasets[1][6][datasets[1][5]])
    if args.baseline:
        import torch
        from .train import PinchTCN, center
        torch.set_num_threads(4)
        checkpoint = torch.load(args.baseline, weights_only=True)
        network = PinchTCN()
        network.load_state_dict(checkpoint['state_dict'])
        network.eval()
        data = datasets[1]
        x = torch.tensor((center(data[0]) / np.asarray(checkpoint['scale'])).transpose(0,2,1), dtype=torch.float32)
        with torch.no_grad():
            prediction = torch.cat([network(v).argmax(1) for v in x.split(128)]).numpy()
        report['tcn_same_windows'] = metrics(data[1][data[5]], prediction[data[5]])
        report['tcn_all_windows'] = metrics(data[1], prediction)
        shutil.copyfile(args.baseline, args.output/'fallback.pt')
        from .predict_features import predict_windows
        combined, fallback = predict_windows(args.output, data[0], data[4], data[5])
        report['combined_all_windows'] = metrics(data[1], combined)
        report['combined_trial_majority'] = trial_metrics(data[1], combined, data[6])
        report['fallback_windows'] = int(fallback.sum())
    source = args.output/'source'
    source.mkdir()
    for name in ('__init__.py','compare.py','features.py','predict_features.py','dataset.py','train.py','labels.py','requirements.txt'):
        shutil.copyfile(Path(__file__).parent/name, source/name)
    report['source_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    report['command'] = sys.argv
    (args.output/'comparison.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Selected:', report['winner']['modality'], report['winner']['name'], flush=True)


if __name__ == '__main__':
    main()
