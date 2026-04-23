import hashlib
import csv
import json
import re
from pathlib import Path
from typing import List

from docx import Document as DocxDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader


class DocumentProcessor:
    @staticmethod
    def supported_suffixes() -> set[str]:
        return {".pdf", ".txt", ".md", ".docx", ".csv"}

    @staticmethod
    def supported_image_suffixes() -> set[str]:
        return {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

    def __init__(self, input_dir: Path, data_dir: Path) -> None:
        self.input_dir = input_dir
        self.data_dir = data_dir
        self.index_dir = self.data_dir / "index"
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.meta_file = self.index_dir / "processed_files.json"
        if not self.meta_file.exists():
            self.meta_file.write_text("{}", encoding="utf-8")

    def _load_processed(self) -> dict:
        return json.loads(self.meta_file.read_text(encoding="utf-8"))

    def _save_processed(self, data: dict) -> None:
        self.meta_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _iter_in_subdir(self, subdir: str):
        base = self.input_dir / subdir
        if not base.exists():
            return []
        return [p for p in base.rglob("*") if p.is_file()]

    @staticmethod
    def _clean_text(text: str) -> str:
        lines = text.splitlines()
        cleaned: List[str] = []

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            # Remove probable page headers/footers and page numbers.
            if re.fullmatch(r"\d+", line):
                continue
            if re.search(r"doi|收稿日期|基金项目", line.lower()):
                continue
            cleaned.append(line)

        merged = "\n".join(cleaned)
        # Drop references section if present to reduce retrieval noise.
        marker = re.search(r"\n参考文献\n|\nreferences\n", merged, flags=re.IGNORECASE)
        if marker:
            merged = merged[: marker.start()]

        merged = re.sub(r"\n{3,}", "\n\n", merged)
        return merged.strip()

    @staticmethod
    def _sha256(file_path: Path) -> str:
        h = hashlib.sha256()
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def parse_pdf(self, file_path: Path) -> str:
        reader = PdfReader(str(file_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return self._clean_text("\n".join(pages))

    def parse_csv(self, file_path: Path) -> str:
        rows: list[dict] = []
        with file_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                rows.append(row)
                if i >= 1999:
                    break

        if not rows:
            return ""

        columns = list(rows[0].keys())
        profile_lines = [
            f"CSV文件：{file_path.name}",
            f"总行数(采样)：{len(rows)}",
            f"字段：{columns}",
        ]

        # Build lightweight field profiling for numeric columns.
        for col in columns[:20]:
            vals = [r.get(col, "") for r in rows]
            non_empty = [v for v in vals if str(v).strip() != ""]
            numeric_vals: list[float] = []
            for v in non_empty:
                try:
                    numeric_vals.append(float(str(v).replace(",", "")))
                except Exception:
                    continue

            if non_empty and len(numeric_vals) >= max(3, len(non_empty) // 3):
                mn = min(numeric_vals)
                mx = max(numeric_vals)
                avg = sum(numeric_vals) / len(numeric_vals)
                profile_lines.append(
                    f"字段[{col}] 数值列：count={len(numeric_vals)}, min={mn:.4g}, max={mx:.4g}, mean={avg:.4g}"
                )
            else:
                uniq = sorted({str(v) for v in non_empty})[:8]
                profile_lines.append(
                    f"字段[{col}] 类别/文本列：非空={len(non_empty)}, 示例值={uniq}"
                )

        sample_rows = rows[:5]
        profile_lines.append("样例记录：")
        for row in sample_rows:
            profile_lines.append(json.dumps(row, ensure_ascii=False))

        return self._clean_text("\n".join(profile_lines))

    def parse_document(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self.parse_pdf(file_path)
        if suffix == ".csv":
            return self.parse_csv(file_path)
        if suffix in {".txt", ".md"}:
            return self._clean_text(file_path.read_text(encoding="utf-8", errors="ignore"))
        if suffix == ".docx":
            doc = DocxDocument(str(file_path))
            text = "\n".join([p.text for p in doc.paragraphs])
            return self._clean_text(text)
        return ""

    def split_text(self, text: str) -> List[str]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=900,
            chunk_overlap=120,
            separators=["\n\n", "\n", "。", ".", " ", ""],
        )
        return splitter.split_text(text)

    def find_new_or_changed_documents(self) -> List[Path]:
        processed = self._load_processed()
        changed: List[Path] = []

        supported_suffixes = self.supported_suffixes()
        text_files = self.list_supported_documents()
        for file_path in text_files:
            digest = self._sha256(file_path)
            source_id = self.source_id(file_path)
            if processed.get(source_id) != digest:
                changed.append(file_path)

        return changed

    def find_incompatible_documents(self) -> List[Path]:
        incompatible: List[Path] = []
        supported_suffixes = self.supported_suffixes()
        for subdir in ("pdf", "csv"):
            for file_path in self._iter_in_subdir(subdir):
                if file_path.suffix.lower() not in supported_suffixes:
                    incompatible.append(file_path)
        return incompatible

    def list_supported_documents(self) -> List[Path]:
        docs: List[Path] = []
        supported_suffixes = self.supported_suffixes()
        for subdir in ("pdf", "csv"):
            for file_path in self._iter_in_subdir(subdir):
                if file_path.suffix.lower() in supported_suffixes:
                    docs.append(file_path)
        return docs

    def list_image_files(self) -> List[Path]:
        images: List[Path] = []
        supported = self.supported_image_suffixes()
        for file_path in self._iter_in_subdir("images"):
            if file_path.suffix.lower() in supported:
                images.append(file_path)
        return images

    def source_id(self, file_path: Path) -> str:
        try:
            return file_path.relative_to(self.input_dir).as_posix()
        except ValueError:
            return file_path.name

    def mark_processed(self, file_path: Path) -> None:
        processed = self._load_processed()
        processed[self.source_id(file_path)] = self._sha256(file_path)
        self._save_processed(processed)
