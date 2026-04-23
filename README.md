# AI 论文写作服务（FastAPI + RAG）

一个可本地运行的论文辅助写作服务，支持三目录输入、异步任务、流式生成与多格式输出。

## 功能概览

- 输入目录拆分：
  - `input/pdf`：PDF 文献
  - `input/csv`：结构化数据
  - `input/images`：图片素材
- 启动时自动增量索引，运行时递归监听三目录新增文件
- 生成任务异步执行，通过 `task_id` 查询进度
- 生成阶段支持终端流式输出
- 输出格式：Markdown、DOCX、Typst（若安装 typst 可编译 PDF）
- 引用映射自动生成，便于后续补全参考文献

## 安装

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

复制环境变量模板：

```bash
copy .env.example .env
```

在 `.env` 中至少配置：

```env
SF_API_KEY=
SF_BASE_URL=
SF_MODEL=
TEMPERATURE=0.2
```

## 运行

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Swagger: `http://127.0.0.1:8001/docs`

## 目录结构

```text
input/
  pdf/
  csv/
  images/
output/
data/
```

## 使用流程

1. 把资料分别放入 `input/pdf`、`input/csv`、`input/images`
2. 启动服务（会自动处理新增/变更文件）
3. 调用 `POST /generate` 提交任务
4. 用 `GET /tasks/{task_id}` 轮询状态
5. 在 `output/` 查看产物

## API

### POST /generate

请求示例：

```json
{
  "title": "人工智能革新生产力统计计算",
  "task_type": "review",
  "tone": "严谨、学术",
  "user_description": "强调实证结果与图表解释",
  "sections": ["摘要", "1. 引言", "2. 方法", "3. 结果", "4. 结论"]
}
```

### GET /tasks/{task_id}

返回任务状态、进度、输出文件和引用映射。

### POST /reindex

手动触发增量重建索引。

### GET /health

健康检查。

## 重要说明（索引一致性）

- 索引 source 标识已统一为相对路径（例如 `pdf/xxx.pdf`）
- 已修复启动清理与增量判定之间的一致性问题：
  - 清理时同时兼容旧标识（仅文件名）与新标识（相对路径）
  - 避免“清理后索引空、但增量判定无变化”的历史问题

