# AI 论文写作初版（FastAPI + RAG）

这是一个可运行的初版产品，支持：

- 监控 `input/` 文件夹中新放入的 PDF，并自动建立索引
- 提供 Swagger 接口提交论文写作任务
- 异步生成论文草稿，返回 `task_id` 查询进度
- 输出 Markdown 和 DOCX 文件
- 自动附带引用映射与参考文献草稿

## 1. 安装

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

必须：配置可用模型 Key（未配置将直接失败）

```bash
copy .env.example .env
```

并在 `.env` 中填写：

```env
SF_API_KEY=
SF_BASE_URL=
SF_MODEL=
TEMPERATURE=0
```

## 2. 运行

```bash
uvicorn app.main:app --reload
```

打开 Swagger：

- http://127.0.0.1:8000/docs

## 3. 使用流程

1. 把 PDF 论文放进 `input/`
2. 启动服务（启动时会索引新增/变更 PDF）
3. 调用 `POST /generate`，传入 `title`、`task_type`、`tone`
4. 用 `GET /tasks/{task_id}` 轮询状态
5. 完成后在 `output/` 查看 `.md` 和 `.docx`

说明：
- 当前推荐输入格式：`.pdf`、`.txt`、`.md`、`.docx`
- `.caj` 不直接兼容，请先转换为 `.pdf`

## 4. API 说明

### `POST /generate`

示例参数：

```json
{
  {
  "title": "llm",
  "task_type": "review",
  "tone": "严谨、客观、学术",
  "sections": [
  "摘要 (Abstract)",
  "引言 (Introduction)",
  "相关工作 (Related Work)",
  "系统架构与方法 (Methodology)",
  "实验与分析 (Results and Discussion)",
  "结论 (Conclusion)",
  "参考文献 (References)"
  ]
}
}
```

### `GET /tasks/{task_id}`

返回任务状态、进度、引用映射、输出文件路径。

### `POST /reindex`

手动触发增量索引。

### `GET /health`

健康检查。

