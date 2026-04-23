import json
import re
from pathlib import Path
from typing import List

from langchain_core.documents import Document


class VectorStoreService:
    def __init__(self, data_dir: Path) -> None:
        self.index_path = data_dir / "simple_index.json"
        self.docs: List[Document] = []
        self._load_or_create()

    def _load_or_create(self) -> None:
        if not self.index_path.exists():
            self.index_path.write_text("[]", encoding="utf-8")
            self.docs = []
            return

        raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        self.docs = [
            Document(page_content=item["page_content"], metadata=item["metadata"])
            for item in raw
        ]

    def _save(self) -> None:
        payload = [
            {"page_content": doc.page_content, "metadata": doc.metadata}
            for doc in self.docs
        ]
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _tokens(text: str) -> set[str]:
        lowered = text.lower()
        # Split English words and Chinese phrases separately to improve mixed-query recall.
        return set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", lowered))

    def add_chunks(self, chunks: List[str], source_file: str) -> None:
        self.docs.extend(
            [Document(page_content=chunk, metadata={"source": source_file}) for chunk in chunks]
        )
        self._save()

    def search(self, query: str, k: int = 8) -> List[Document]:
        if not self.docs:
            return []

        q = self._tokens(query)
        scored: list[tuple[float, Document]] = []
        for doc in self.docs:
            dt = self._tokens(doc.page_content)
            if not dt:
                continue
            inter = len(q & dt)
            union = len(q | dt)
            score = (inter / union) if union else 0.0
            scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for score, doc in scored[:k] if score > 0]
