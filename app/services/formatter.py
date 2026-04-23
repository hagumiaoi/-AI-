from pathlib import Path

from docx import Document


class OutputFormatter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_markdown(self, task_id: str, markdown: str) -> Path:
        md_path = self.output_dir / f"{task_id}.md"
        md_path.write_text(markdown, encoding="utf-8")
        return md_path

    def save_docx(self, task_id: str, markdown: str) -> Path:
        doc = Document()
        for line in markdown.splitlines():
            line = line.strip()
            if not line:
                doc.add_paragraph("")
                continue
            if line.startswith("# "):
                doc.add_heading(line[2:].strip(), level=1)
            elif line.startswith("## "):
                doc.add_heading(line[3:].strip(), level=2)
            elif line.startswith("### "):
                doc.add_heading(line[4:].strip(), level=3)
            else:
                doc.add_paragraph(line)

        docx_path = self.output_dir / f"{task_id}.docx"
        doc.save(docx_path)
        return docx_path
