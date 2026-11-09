from pathlib import Path
from tempfile import TemporaryDirectory as _TemporaryDirectory

def TemporaryDirectory(*args, **kwargs):
    directory = kwargs.get('dir')
    if directory is not None:
        Path(directory).mkdir(parents=True, exist_ok=True)
    return _TemporaryDirectory(*args, **kwargs)
