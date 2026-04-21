import torch
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"CUDA version: {torch.version.cuda}")

import PySide6
print(f"\nPySide6 version: {PySide6.__version__}")

import decord
print(f"decord version: {decord.__version__}")

print("\nAll good — stack is live.")