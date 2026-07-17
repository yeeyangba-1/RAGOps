# RAGOps

RAGOps 是面向知识库场景的 RAG 应用质量评测与持续优化 SDK。当前 SDK
提供统一 Trace 数据模型、JSONL 本地持久化，以及不绑定具体 RAG 框架的
`TracedRagRunner` 接入层。

项目目标是基于 StudyRAG 和 SearchInsight 两个原型，逐步形成工程化、可复用的
RAG 质量基础设施；当前版本不包含 Evaluation、Agent、API 或数据库。

## 安装

开发环境可以从仓库根目录执行 editable install：

```bash
python -m pip install -e ".[dev]"
```

标准导入方式：

```python
from ragops.tracing import RagTracePayload, TraceCollector, TracedRagRunner
```

## TracedRagRunner 示例

```python
from pathlib import Path

from ragops.tracing import RagTracePayload, TraceCollector, TracedRagRunner


def rag_pipeline(query: str) -> dict:
    return {
        "answer": "示例回答",
        "chunks": ["示例检索片段"],
        "scores": [0.91],
    }


def map_result(result: dict) -> RagTracePayload:
    return RagTracePayload(
        retrieval_chunks=result["chunks"],
        retrieval_scores=result["scores"],
        answer=result["answer"],
    )


runner = TracedRagRunner(
    TraceCollector(Path("outputs") / "ragops_traces.jsonl"),
    result_mapper=map_result,
    prompt_version="qa_v1",
    model="deepseek-chat",
)

run = runner.run("用户问题", rag_pipeline)
print(run.result)
print(run.trace_id)
```

## Trace 保存失败策略

`fail_open=True` 是默认行为。Pipeline 成功后，如果结果映射、Trace 校验或持久化
失败，Runner 会记录异常日志，并返回未经修改的 Pipeline 结果；此时
`trace_id` 为 `None`。Pipeline 本身的异常始终原样抛出。

设置 `fail_open=False` 后，Trace 阶段的异常会原样抛出。无论使用哪种模式，
Runner 都不会为了恢复 Trace 而重复调用 Pipeline。
