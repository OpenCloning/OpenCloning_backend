import os

from uvicorn.workers import UvicornWorker


class OpenCloningUvicornWorker(UvicornWorker):
    """Uvicorn worker that honors ROOT_PATH when the app is served under a subpath."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        root_path = os.environ.get('ROOT_PATH', '').strip()
        if root_path:
            self.config.root_path = root_path
