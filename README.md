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
  "sections": [ 
  "摘要",
  "引言",
  "数据建模",
  "实证分析",
  "结论",
  "参考文献"]
}
```

⚠需求描述怎么写

- 你每次想告诉 AI 的具体要求，都写在 `user_description` 字段。
- 推荐写法：
  - 写清目标：你最终要什么结果。
  - 写清约束：篇幅、结构、语气、必须包含/禁止包含的内容。
  - 写清侧重点：方法优先、结果优先、图表解释优先等。
- 示例：
  - `请按中文核心期刊风格写作，优先突出实证结果与政策含义；每个一级章节至少2段；方法部分必须解释变量定义与模型设定；可结合 input/images 中图表进行结果解读。`

补充说明：

- `tone` 适合放一句话风格（如：严谨、客观）。
- `user_description` 放完整任务要求（你最关心的内容）。
- 如果你想长期修改写作规则，可编辑 `prompt_templates.txt`（系统级提示词模板）。

### GET /tasks/{task_id}

返回任务状态、进度、输出文件和引用映射。

### POST /reindex

手动触发增量重建索引。

### GET /health

健康检查。


