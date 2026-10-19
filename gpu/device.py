"""
Which device the tensors live on.

Cadenza wants the GPU and is built around having one, but it has to run
without it — slower, not broken. Several places used to name 'cuda'
outright, which turned a missing GPU into an AssertionError from torch
deep inside frame compositing, where it was caught and logged as a
dropped frame rather than reported.

Ask here instead, or take the device from a tensor already in hand.
"""

import torch

_cached = None


def compute_device() -> torch.device:
    """The best device available, worked out once."""
    global _cached
    if _cached is None:
        try:
            _cached = torch.device(
                'cuda' if torch.cuda.is_available() else 'cpu')
        except Exception:
            _cached = torch.device('cpu')
    return _cached


def have_gpu() -> bool:
    return compute_device().type == 'cuda'
