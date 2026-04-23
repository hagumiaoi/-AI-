import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.models import GenerateRequest


DEFAULT_PROMPTS = {
    "EVIDENCE_SYSTEM": (
        "你是学术证据整理助手。仅提炼事实要点，不写成论文段落。"
        "输出4-8条要点，每条简短，附来源编号占位。"
    ),
    "EVIDENCE_USER": (
        "章节：{section_title}\n"
        "请从以下文献片段中提炼可用于该章节的证据要点：\n\n"
        "{context_text}"
    ),
    "WRITE_SYSTEM": (
        "你是学术论文作者。你的任务是基于证据进行综合改写，而不是摘抄原句。"
        "必须遵守："
        "1) 避免直接复制证据原句；"
        "2) 不要出现连续12个字与证据完全相同；"
        "3) 保持学术语气，给出归纳、比较和解释；"
        "4) 每段包含至少一个引用标记，如[1]。"
    ),
    "WRITE_USER": (
        "论文标题：{title}\n"
        "风格要求：{tone}\n"
        "当前章节：{section_title}\n"
        "引用映射：{citation_hint}\n\n"
        "已写内容（避免重复）：\n{prev_context}\n\n"
        "可用证据要点：\n{evidence_summary}\n\n"
        "请写该章节的完整正文（中文Markdown，不含章节标题）。"
    ),
}


@dataclass
class GenerationResult:
    markdown: str
    citations: Dict[str, str]


class PaperGenerator:
    def __init__(self) -> None:
        self.api_key = (
            os.getenv("OPENAI_API_KEY", "").strip()
            or os.getenv("SF_API_KEY", "").strip()
        )
        self.base_url = (
            os.getenv("OPENAI_BASE_URL", "").strip()
            or os.getenv("SF_BASE_URL", "").strip()
        )
        self.model_name = (
            os.getenv("LLM_MODEL", "").strip()
            or os.getenv("SF_MODEL", "").strip()
            or "gpt-4o-mini"
        )
        self.temperature = float(os.getenv("TEMPERATURE", "0.2"))
        self.prompt_file = Path(__file__).resolve().parents[2] / "prompt_templates.txt"
        self.prompts = self._load_prompt_templates()

    def can_call_llm(self) -> bool:
        return bool(self.api_key)

    def _load_prompt_templates(self) -> Dict[str, str]:
        prompts = dict(DEFAULT_PROMPTS)
        if not self.prompt_file.exists():
            return prompts

        text = self.prompt_file.read_text(encoding="utf-8", errors="ignore")
        matches = list(re.finditer(r"^###\s*([A-Z_]+)\s*$", text, flags=re.MULTILINE))
        if not matches:
            return prompts

        for i, match in enumerate(matches):
            key = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            if key in prompts and content:
                prompts[key] = content
        return prompts

    @staticmethod
    def _render(template: str, **kwargs) -> str:
        try:
            return template.format(**kwargs)
        except KeyError as exc:
            raise RuntimeError(f"Prompt 模板缺少变量: {exc}") from exc

    def _new_llm(self) -> ChatOpenAI:
        kwargs = {
            "model": self.model_name,
            "temperature": self.temperature,
            "api_key": self.api_key,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return ChatOpenAI(**kwargs)

    def _build_outline(self, request: GenerateRequest) -> List[str]:
        if request.sections:
            return request.sections

        if request.task_type.value == "data_analysis":
            return [
                "摘要",
                "1. 引言",
                "2. 数据与方法",
                "3. 实验与结果",
                "4. 讨论",
                "5. 结论",
            ]

        return [
            "摘要",
            "1. 引言",
            "2. 相关研究",
            "3. 方法与实现",
            "4. 结果与讨论",
            "5. 结论",
        ]

    @staticmethod
    def _build_mapping(context_docs: list) -> Dict[str, str]:
        mapping = OrderedDict()
        idx = 1
        for doc in context_docs:
            source = doc.metadata.get("source", "unknown.pdf")
            if source not in mapping.values():
                mapping[str(idx)] = source
                idx += 1
        return mapping

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text.lower()))

    def _select_context_for_section(
        self, section_title: str, request_title: str, context_docs: list, k: int = 4
    ) -> list:
        q = self._tokens(f"{request_title} {section_title}")
        scored: list[tuple[float, object]] = []
        for doc in context_docs:
            dt = self._tokens(doc.page_content)
            if not dt:
                continue
            inter = len(q & dt)
            union = len(q | dt)
            score = (inter / union) if union else 0.0
            scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:k]]

    def _summarize_evidence(self, llm: ChatOpenAI, section_title: str, section_docs: list) -> str:
        if not section_docs:
            return ""
        context_text = "\n\n".join(
            [
                f"[Source: {doc.metadata.get('source', 'unknown.pdf')}]\n{doc.page_content[:1200]}"
                for doc in section_docs
            ]
        )
        messages = [
            SystemMessage(
                content=self.prompts["EVIDENCE_SYSTEM"]
            ),
            HumanMessage(
                content=self._render(
                    self.prompts["EVIDENCE_USER"],
                    section_title=section_title,
                    context_text=context_text,
                )
            ),
        ]
        return llm.invoke(messages).content

    def _write_section(
        self,
        llm: ChatOpenAI,
        request: GenerateRequest,
        section_title: str,
        evidence_summary: str,
        citation_hint: str,
        written_sections: list[str],
        image_context: str,
        stream_callback: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        prev_context = "\n\n".join(written_sections[-2:]) if written_sections else ""
        messages = [
            SystemMessage(
                content=self.prompts["WRITE_SYSTEM"]
            ),
            HumanMessage(
                content=self._render(
                    self.prompts["WRITE_USER"],
                    title=request.title,
                    tone=request.tone,
                    section_title=section_title,
                    citation_hint=citation_hint,
                    prev_context=prev_context,
                    evidence_summary=evidence_summary,
                    user_description=(request.user_description or ""),
                    image_context=image_context,
                )
            ),
        ]

        # Stream tokens to callback for real-time terminal display.
        if stream_callback:
            chunks: list[str] = []
            try:
                for chunk in llm.stream(messages):
                    text = chunk.content if isinstance(chunk.content, str) else ""
                    if not text:
                        continue
                    chunks.append(text)
                    stream_callback(section_title, text)
                return "".join(chunks)
            except Exception:
                # Fallback to non-streaming call when provider/model does not support streaming.
                return llm.invoke(messages).content

        return llm.invoke(messages).content

    def _llm_generate(
        self,
        request: GenerateRequest,
        outline: List[str],
        context_docs: list,
        citations: Dict[str, str],
        image_files: Optional[List[Path]] = None,
        stream_callback: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        llm = self._new_llm()
        citation_hint = ", ".join([f"[{k}]={v}" for k, v in citations.items()])
        image_files = image_files or []
        image_context = "\n".join(
            [
                f"- 可用图像: {p.as_posix()}"
                for p in image_files[:20]
            ]
        )
        parts = [f"# {request.title}\n"]
        written_sections: list[str] = []

        for section in outline:
            section_docs = self._select_context_for_section(section, request.title, context_docs, k=4)
            evidence = self._summarize_evidence(llm, section, section_docs)
            body = self._write_section(
                llm=llm,
                request=request,
                section_title=section,
                evidence_summary=evidence,
                citation_hint=citation_hint,
                written_sections=written_sections,
                image_context=image_context,
                stream_callback=stream_callback,
            )
            parts.append(f"## {section}\n")
            parts.append(body.strip())
            parts.append("\n")
            written_sections.append(body.strip())

        return "\n".join(parts)

    def generate(
        self,
        request: GenerateRequest,
        context_docs: list,
        image_files: Optional[List[Path]] = None,
        stream_callback: Optional[Callable[[str, str], None]] = None,
    ) -> GenerationResult:
        if not self.can_call_llm():
            raise RuntimeError("未配置可用模型 API Key，无法生成论文。")

        outline = self._build_outline(request)
        citations = self._build_mapping(context_docs)
        markdown = self._llm_generate(
            request,
            outline,
            context_docs,
            citations,
            image_files=image_files,
            stream_callback=stream_callback,
        )

        refs = ["\n## 参考文献\n"]
        for idx, source in citations.items():
            refs.append(f"[{idx}] {source}. 未知作者. 未知年份. (请后续人工补全 GB/T 7714 细节)")

        final_markdown = markdown + "\n" + "\n".join(refs)
        return GenerationResult(markdown=final_markdown, citations=dict(citations))
