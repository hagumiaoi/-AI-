# 1. 路径准备：确保 input, output, data 文件夹存在，防止报错
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

if (BASE_DIR / ".env").exists():
    load_dotenv(BASE_DIR / ".env", override=True)
elif (BASE_DIR / ".env.example").exists():
    load_dotenv(BASE_DIR / ".env.example", override=False)

INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="AI 论文写作初版 API",
    description="基于 FastAPI + RAG 的论文草稿生成服务",
    version="0.1.0",
)


task_manager = TaskManager()
doc_processor = DocumentProcessor(INPUT_DIR, DATA_DIR)
vector_store = VectorStoreService(DATA_DIR)
formatter = OutputFormatter(OUTPUT_DIR)
generator = PaperGenerator()
watcher: FileWatcher | None = None


async def reindex_document(file_path: Path) -> None:
    try:
        text = doc_processor.parse_document(file_path)
        if not text:
            return
        chunks = doc_processor.split_text(text)
        vector_store.add_chunks(chunks, file_path.name)
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
    vector_store.prune_sources({p.name for p in current_docs})

    for file_path in doc_processor.find_new_or_changed_documents():
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
    vector_store.prune_sources({p.name for p in current_docs})

    changed = doc_processor.find_new_or_changed_documents()
    for file_path in changed:
        await reindex_document(file_path)
    return {"indexed": [p.name for p in changed], "count": len(changed)}


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
            hint += " 当前仅支持：pdf、txt、md、docx。若你使用 caj，请先转换为 pdf。"
            hint += " 若已放入 PDF，请先调用 /reindex 确保文献已入库。"
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
        result = generator.generate(request, docs)

        task_manager.update(
            task_id,
            progress=80,
            stage="formatting",
            detail="正在输出 Markdown 与 DOCX",
        )
        md_file = formatter.save_markdown(task_id, result.markdown)
        docx_file = formatter.save_docx(task_id, result.markdown)

        task_manager.update(
            task_id,
            status=TaskStatus.completed,
            progress=100,
            stage="done",
            detail="完成",
            output_files=[str(md_file), str(docx_file)],
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
