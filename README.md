# RAGOps

RAGOps 是面向知识库场景的 RAG 应用质量评测与持续优化 SDK。当前 SDK
提供统一 Trace 数据模型、JSONL 本地持久化，以及不绑定具体 RAG 框架的
`TracedRagRunner` 接入层。

项目目标是基于 StudyRAG 和 SearchInsight 两个原型，逐步形成工程化、可复用的
RAG 质量基础设施。当前版本包含本地、确定性的规则 Evaluation MVP，但不包含
Agent、API 或数据库。

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
    model="example-model",
)

run = runner.run("用户问题", rag_pipeline)
print(run.result)
print(run.trace_id)
```

## Evaluation MVP

`RuleBasedEvaluator` 可以直接评估已有 Trace，不调用网络或大模型：

```python
from ragops.evaluation import RuleBasedEvaluator
from ragops.schemas import Trace

trace = Trace(
    query="示例问题",
    retrieval_chunks=["示例检索片段"],
    retrieval_scores=[0.91],
    prompt_version="qa_v1",
    model="example-model",
    answer="示例回答",
    latency_ms=842,
)

result = RuleBasedEvaluator().evaluate(trace)
print(result.passed)
print(result.issues)
```

批量评估会保持输入顺序，并汇总通过率和各类问题次数：

```python
traces = [
    trace,
    Trace(
        query="另一个示例问题",
        retrieval_chunks=[],
        retrieval_scores=[],
        prompt_version="qa_v1",
        model="example-model",
        answer="没有找到相关内容。",
        latency_ms=615,
    ),
]

report = RuleBasedEvaluator().evaluate_many(traces)
print(report.total_count)
print(report.pass_rate)
print(report.issue_counts)
```

## 离线评估

本地 Trace JSONL 可以通过规则评估器生成并保存一个 EvaluationReport：

```python
from pathlib import Path

from ragops.evaluation import (
    EvaluationReportCollector,
    OfflineEvaluationRunner,
    RuleBasedEvaluator,
)
from ragops.tracing import TraceCollector

runner = OfflineEvaluationRunner(
    TraceCollector(Path("outputs") / "ragops_traces.jsonl"),
    RuleBasedEvaluator(),
    EvaluationReportCollector(Path("outputs") / "evaluation_reports.jsonl"),
)

report = runner.run()
print(report.report_id)
print(report.total_count)
print(report.pass_rate)
print(report.failed_trace_ids)
```

当前离线评估是面向本地单进程使用的 JSONL MVP。

## 坏案例分析

`IssueAnalyzer` 将评估失败结果与原始 Trace 关联，并直接使用已有 issue 分组：

```python
from pathlib import Path

from ragops.analysis import IssueAnalyzer
from ragops.evaluation import EvaluationReportCollector
from ragops.tracing import TraceCollector

traces = TraceCollector(
    Path("outputs") / "ragops_traces.jsonl"
).list_traces()
reports = EvaluationReportCollector(
    Path("outputs") / "evaluation_reports.jsonl"
).list_reports()

analysis = IssueAnalyzer().analyze(reports[-1], traces)
print(analysis.total_bad_cases)
print(analysis.issue_groups)

for bad_case in analysis.bad_cases:
    print(bad_case.trace.query)
    print(bad_case.trace.answer)
    print(bad_case.evaluation.issues)
```

## 实验结果对比

`ExperimentComparator` 比较两份已经生成、且覆盖相同 Trace 集合的评估报告：

```python
from pathlib import Path

from ragops.evaluation import EvaluationReportCollector
from ragops.experiments import ExperimentComparator

reports = EvaluationReportCollector(
    Path("outputs") / "evaluation_reports.jsonl"
).list_reports()
baseline_report, candidate_report = reports[-2:]

comparison = ExperimentComparator().compare(
    baseline_report,
    candidate_report,
)
print(comparison.pass_rate_delta)
print(comparison.improved_trace_ids)
print(comparison.regressed_trace_ids)
print(comparison.issue_count_deltas)
```

当前只比较已有 `EvaluationReport`。负的 issue delta 表示候选报告中的该问题数量减少。

## Trace 保存失败策略

`fail_open=True` 是默认行为。Pipeline 成功后，如果结果映射、Trace 校验或持久化
失败，Runner 会记录异常日志，并返回未经修改的 Pipeline 结果；此时
`trace_id` 为 `None`。Pipeline 本身的异常始终原样抛出。

设置 `fail_open=False` 后，Trace 阶段的异常会原样抛出。无论使用哪种模式，
Runner 都不会为了恢复 Trace 而重复调用 Pipeline。
