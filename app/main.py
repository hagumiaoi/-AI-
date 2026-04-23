
import asyncio
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from dotenv import load_dotenv

from app.models import GenerateRequest, GenerateResponse, TaskStatus
from app.services.document_processor import DocumentProcessor
from app.services.file_watcher import FileWatcher
from app.services.formatter import OutputFormatter
from app.services.generator import PaperGenerator
from app.services.task_manager import TaskManager
from app.services.vector_store import VectorStoreService

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
DATA_DIR = BASE_DIR / "data"
PDF_DIR = INPUT_DIR / "pdf"
CSV_DIR = INPUT_DIR / "csv"
IMAGES_DIR = INPUT_DIR / "images"

if (BASE_DIR / ".env").exists():
    load_dotenv(BASE_DIR / ".env", override=True)
elif (BASE_DIR / ".env.example").exists():
    load_dotenv(BASE_DIR / ".env.example", override=False)
    
# 1. 路径准备：确保 input, output, data 文件夹存在，防止报错
INPUT_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR.mkdir(parents=True, exist_ok=True)
CSV_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="AI 论文辅助写作",
    description="基于 FastAPI + RAG 的论文草稿生成服务",
    version="0.1.0",
)


task_manager = TaskManager()
doc_processor = DocumentProcessor(INPUT_DIR, DATA_DIR)
vector_store = VectorStoreService(DATA_DIR)
formatter = OutputFormatter(OUTPUT_DIR)
generator = PaperGenerator()
watcher: FileWatcher | None = None


def _build_allowed_sources(current_docs: list[Path]) -> set[str]:
    allowed: set[str] = set()
    for p in current_docs:
        sid = doc_processor.source_id(p)
        allowed.add(sid)
        # Keep legacy basename source ids for backward compatibility.
        allowed.add(p.name)
    return allowed


async def reindex_document(file_path: Path) -> None:
    try:
        text = doc_processor.parse_document(file_path)
        if not text:
            return
        chunks = doc_processor.split_text(text)
        vector_store.add_chunks(chunks, doc_processor.source_id(file_path))
        doc_processor.mark_processed(file_path)
    except Exception:
        # Skip unreadable/locked files and continue indexing others.
        return


def reindex_document_sync(file_path: Path) -> None:
    asyncio.run(reindex_document(file_path))


@app.on_event("startup")
async def startup_event() -> None:
    global watcher
    current_docs = doc_processor.list_supported_documents()
    vector_store.prune_sources(_build_allowed_sources(current_docs))

    changed_docs = doc_processor.find_new_or_changed_documents()

    for file_path in changed_docs:
        await reindex_document(file_path)

    watcher = FileWatcher(INPUT_DIR, reindex_document_sync)
    watcher.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    if watcher:
        watcher.stop()


@app.post("/generate", response_model=GenerateResponse, tags=["generation"])
async def generate_paper(request: GenerateRequest, background_tasks: BackgroundTasks):
    task = task_manager.create_task()
    background_tasks.add_task(_run_generation_task, task.task_id, request)
    return GenerateResponse(
        task_id=task.task_id,
        message="任务已创建，请调用 /tasks/{task_id} 查询进度",
    )


@app.get("/tasks/{task_id}", tags=["generation"])
async def get_task(task_id: str):
    task = task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task_id 不存在")
    return task


@app.post("/reindex", tags=["index"])
async def manual_reindex() -> dict:
    current_docs = doc_processor.list_supported_documents()
    vector_store.prune_sources(_build_allowed_sources(current_docs))

    changed = doc_processor.find_new_or_changed_documents()

    for file_path in changed:
        await reindex_document(file_path)
    return {
        "indexed": [doc_processor.source_id(p) for p in changed],
        "count": len(changed),
    }


def _run_generation_task(task_id: str, request: GenerateRequest) -> None:
    try:
        task_manager.update(
            task_id,
            status=TaskStatus.running,
            progress=5,
            stage="retrieval",
            detail="正在检索相关论文内容",
        )
        docs = vector_store.search(request.title, k=12)
        if not docs:
            docs = vector_store.get_documents(k=12)

        if not docs:
            incompatible = [p.name for p in doc_processor.find_incompatible_documents()]
            hint = "未检索到可用文献内容。"
            if incompatible:
                hint += f" 检测到不兼容格式文件：{incompatible}。"
            hint += " 当前文本输入目录支持：input/pdf(仅pdf)、input/csv(仅csv)。"
            hint += " 若你使用 caj，请先转换为 pdf 并放入 input/pdf。"
            hint += " 若已放入文件，请先调用 /reindex 确保内容已入库。"
            task_manager.update(
                task_id,
                status=TaskStatus.failed,
                progress=100,
                stage="failed",
                detail="失败",
                error=hint,
            )
            return

        if not generator.can_call_llm():
            task_manager.update(
                task_id,
                status=TaskStatus.failed,
                progress=100,
                stage="failed",
                detail="失败",
                error="未配置模型 API Key，无法生成论文。",
            )
            return

        task_manager.update(
            task_id,
            progress=40,
            stage="generation",
            detail="正在生成论文初稿",
        )

        last_section = {"name": ""}
        stream_buffer = {"text": ""}

        def stream_to_terminal(section: str, token: str) -> None:
            if section != last_section["name"]:
                if stream_buffer["text"]:
                    print(f"[StreamingText] {stream_buffer['text']}", flush=True)
                    stream_buffer["text"] = ""
                last_section["name"] = section
                print(f"\n[Streaming] section={section}", flush=True)
            stream_buffer["text"] += token
            # Print in short chunks with newline so terminal/collector can render progressively.
            if len(stream_buffer["text"]) >= 80 or token in {"\n", "。", "！", "？"}:
                print(f"[StreamingText] {stream_buffer['text']}", flush=True)
                stream_buffer["text"] = ""

        image_files = doc_processor.list_image_files()
        result = generator.generate(
            request,
            docs,
            image_files=image_files,
            stream_callback=stream_to_terminal,
        )
        if stream_buffer["text"]:
            print(f"[StreamingText] {stream_buffer['text']}", flush=True)
        print("\n[Streaming] generation completed", flush=True)

        task_manager.update(
            task_id,
            progress=80,
            stage="formatting",
            detail="正在输出 Markdown、DOCX、Typst/PDF",
        )
        md_file = formatter.save_markdown(task_id, result.markdown)
        docx_file = formatter.save_docx(task_id, result.markdown)
        typ_file = formatter.save_typst(task_id, result.markdown)
        pdf_file = formatter.compile_typst_pdf(typ_file)

        outputs = [str(md_file), str(docx_file), str(typ_file)]
        if pdf_file:
            outputs.append(str(pdf_file))

        task_manager.update(
            task_id,
            status=TaskStatus.completed,
            progress=100,
            stage="done",
            detail="完成",
            output_files=outputs,
            citations=result.citations,
        )
    except Exception as exc:
        task_manager.update(
            task_id,
            status=TaskStatus.failed,
            progress=100,
            stage="failed",
            detail="失败",
            error=str(exc),
        )


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "input_dir": str(INPUT_DIR), "output_dir": str(OUTPUT_DIR)}
