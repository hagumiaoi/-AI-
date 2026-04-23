from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    review = "review"
    data_analysis = "data_analysis"
    custom = "custom"


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class GenerateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=200, description="论文标题")
    task_type: TaskType = Field(default=TaskType.review, description="任务类型")
    tone: str = Field(default="严谨、客观、学术", description="风格要求")
    sections: Optional[List[str]] = Field(
        default=None,
        description="可选，指定章节列表。未指定则自动生成标准学术结构",
    )


class GenerateResponse(BaseModel):
    task_id: str
    message: str


class TaskProgress(BaseModel):
    task_id: str
    status: TaskStatus
    progress: int = Field(default=0, ge=0, le=100)
    stage: str = "initialized"
    detail: str = ""
    output_files: List[str] = Field(default_factory=list)
    citations: Dict[str, str] = Field(default_factory=dict)
    error: Optional[str] = None
