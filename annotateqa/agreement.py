"""Metrics for repeated annotations by one person: intra-rater, not inter-rater."""
import warnings
from sklearn.metrics import cohen_kappa_score, confusion_matrix
from sklearn.exceptions import UndefinedMetricWarning
from backend.domain import LABELS

def calculate_agreement(first, second):
    if len(first) != len(second):
        raise ValueError('Passes must contain the same paired clips.')
    n = len(first)
    if not n:
        return {'n': 0, 'agreement_pct': None, 'kappa': None, 'kappa_note': 'No paired annotations yet.', 'labels': LABELS, 'matrix': [[0] * len(LABELS) for _ in LABELS]}
    observed = sum(a == b for a, b in zip(first, second)) / n
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        warnings.simplefilter('ignore', UndefinedMetricWarning)
        value = float(cohen_kappa_score(first, second, labels=LABELS))
    import math
    valid = math.isfinite(value)
    return {'n': n, 'agreement_pct': round(observed * 100, 2), 'kappa': round(value, 4) if valid else None,
            'kappa_note': None if valid else 'Undefined: no label variation; chance agreement is 100%.',
            'labels': LABELS, 'matrix': confusion_matrix(first, second, labels=LABELS).tolist()}
