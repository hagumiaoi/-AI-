from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class _DocumentEventHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback
        self.supported_suffixes = (".pdf", ".txt", ".md", ".docx")

    def on_created(self, event):
        if event.is_directory:
            return
        if str(event.src_path).lower().endswith(self.supported_suffixes):
            self.callback(Path(event.src_path))


class FileWatcher:
    def __init__(self, input_dir: Path, on_document_added):
        self.input_dir = input_dir
        self.on_document_added = on_document_added
        self.observer = Observer()

    def start(self) -> None:
        handler = _DocumentEventHandler(self.on_document_added)
        self.observer.schedule(handler, str(self.input_dir), recursive=False)
        self.observer.start()

    def stop(self) -> None:
        self.observer.stop()
        self.observer.join(timeout=3)
