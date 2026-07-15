# RAGOps Trace Contract 设计

## 0. 文档状态与范围

- 阶段：Sprint 1 / Trace Contract 设计
- 状态：Draft for review
- 输入：`ARCHITECTURE.md`、`DESIGN_DECISIONS.md`、`CODE_AUDIT.md`
- 范围：一次完整 RAG 请求的逻辑数据契约
- 非范围：代码、数据库表、API、Agent、具体存储实现

本文中的 JSON 是跨模块交换和导入导出的**逻辑聚合视图**，不是数据库表设计。后续即使内部采用关系模型、对象存储或事件流，也必须能无损生成该视图。

## 1. Trace 在 RAGOps 中的作用

Trace 是一次 RAG 请求从接收用户问题到返回答案的事实记录。它回答六个核心问题：

1. 谁在什么上下文中提出了什么问题？
2. 当时固定了哪些知识库、索引、Prompt、模型和代码版本？
3. 系统实际检索了什么，哪些片段进入了模型上下文？
4. 模型实际看到了什么 Prompt，并生成了什么结果？
5. 每个阶段是否成功，耗时、token 和成本是多少？
6. 用户或评测人员后来如何评价这次结果？

Trace 在 RAGOps 中同时承担四种职责：

- **调试事实：** 通过 `trace_id` 还原一次请求的每个阶段，而不是只看 query/answer。
- **评测输入：** 检索、生成、性能和反馈 evaluator 读取同一份事实数据。
- **问题证据：** Bad Case 必须关联具体 trace、hit、Prompt 或 generation，而不是只给文字结论。
- **实验样本：** baseline 与 variant 在相同 case 下产生独立 trace，才能比较质量、延迟和成本。

Trace 不等于系统遥测：

- RAG Trace 是业务质量事实，关注 query、证据、版本和答案。
- OpenTelemetry trace 是系统运行遥测，关注进程、网络、span 和基础设施故障。
- 两者通过 `trace_id`/`otel_trace_id` 关联，但不使用同一个 schema。

## 2. 设计原则

### 2.1 版本化

契约自身有 `schema_version`；知识库、索引、retrieval、Prompt、模型和代码也都以不可变版本 ID 绑定。版本只新增，不原地覆盖。

### 2.2 可重放

只记录配置名称不够。Trace 必须保存版本引用、精确的检索结果、最终渲染 Prompt、模型参数和内容哈希，使后续能够区分“重放同一输入”和“重新执行相同配置”。

### 2.3 阶段失败显式化

Trace 和 retrieval、prompt、generation 分别记录状态与错误。失败、取消、跳过、部分成功和降级不能伪装为 `succeeded`。

### 2.4 在线与离线同构

线上用户请求、离线评测、历史重放和实验变体使用同一个核心契约，通过 `run_context.mode` 和关联 ID 区分来源。

### 2.5 事实与判断分离

Trace 保存发生了什么；评测分数、Bad Case 标签和优化建议属于独立的 evaluator/issue 数据，通过 `trace_id` 关联。这样可以在不篡改历史 Trace 的情况下重复评测。

### 2.6 隐私与最小化

用户标识默认使用不可逆引用；metadata 使用白名单；query、Prompt、chunk 和 answer 按数据分级、脱敏策略和保留期处理。

## 3. Trace 逻辑结构

```text
Trace
├── envelope                 # schema、身份、状态和时间
├── run_context              # online/evaluation/replay/experiment 关联
├── request                  # 用户请求与会话上下文
├── versions                 # 本次运行固定的不可变版本
├── retrieval                # 检索输入、策略、结果和错误
│   └── hits[]               # 文档片段、来源、rank 和 score
├── prompt                   # Prompt 版本与实际渲染消息
├── model                    # 实际调用的 provider、模型和参数
├── generation               # 答案、引用、拒答、usage 和错误
├── performance              # 分阶段耗时、尝试次数和成本
├── feedback[]               # 可在请求结束后追加的反馈事实
├── observability            # 与系统遥测的关联
└── governance               # 数据分级、脱敏和保留策略
```

字段必要性使用以下标记：

- `R`：所有合法 Trace 必填。
- `C`：满足特定条件时必填。
- `O`：可选；未知时使用 `null` 或空集合，不伪造值。

## 4. 字段设计与存在理由

### 4.1 Trace 信封与运行上下文

| 字段路径 | 必要性 | 类型/约束 | 为什么存在 |
|---|---:|---|---|
| `schema_version` | R | 语义版本字符串 | 允许契约演进、兼容校验和迁移 |
| `trace_id` | R | 全局唯一稳定 ID | 连接运行、评测、Issue、实验和系统遥测 |
| `revision` | R | 从 1 递增 | Feedback 等后到数据追加后，区分 Trace 快照版本 |
| `workspace_id` | R | 稳定 ID | 权限、隔离和保留策略边界 |
| `project_id` | R | 稳定 ID | 标识具体 RAG 应用，支持跨项目隔离和聚合 |
| `environment` | R | `dev/test/staging/prod` 等受控枚举 | 避免把测试与生产结果混合比较 |
| `status` | R | `pending/running/succeeded/partial/failed/cancelled` | 表达端到端最终状态，防止不完整数据被当作成功样本 |
| `started_at` | R | UTC ISO 8601 | 排序、趋势、SLA 和时间切片 |
| `ended_at` | C | 终态必填，UTC ISO 8601 | 计算总耗时并判断运行是否结束 |
| `recorded_at` | R | UTC ISO 8601 | 区分业务发生时间和 Trace 首次持久化时间 |
| `updated_at` | R | UTC ISO 8601 | 标识 Feedback 追加或状态修正后的最新快照时间 |
| `run_context.mode` | R | `online/evaluation/replay/experiment` | 让线上与离线使用同一 schema，同时能正确切片 |
| `run_context.parent_trace_id` | O | Trace ID 或 `null` | 表示重试、重放或派生运行的来源，不覆盖原运行 |
| `run_context.evaluation_run_id` | C | evaluation 模式必填 | 将 Trace 绑定到一次可复现评测批次 |
| `run_context.evaluation_case_id` | C | evaluation/experiment 模式必填 | 将结果绑定到固定数据集样本 |
| `run_context.experiment_id` | C | experiment 模式必填 | 关联 baseline/variant 所属实验 |
| `run_context.variant_id` | C | experiment 模式必填 | 标识本 Trace 使用的实验变体 |
| `run_context.pairing_key` | C | 成对比较时必填 | 确保 baseline 与 variant 比较的是同一 case |

### 4.2 用户请求信息 `request`

| 字段路径 | 必要性 | 类型/约束 | 为什么存在 |
|---|---:|---|---|
| `request.request_id` | R | 客户端或接入层唯一 ID | 支持幂等、请求去重和跨系统排查 |
| `request.submitted_at` | R | UTC ISO 8601 | 区分排队时间和真正开始处理时间 |
| `request.session_id` | O | 会话 ID | 支持多轮会话切片；不得直接包含敏感身份信息 |
| `request.user_ref` | O | 脱敏/哈希用户引用 | 分析重复反馈和用户切片，同时降低 PII 风险 |
| `request.channel` | R | `web/api/cli/batch` 等受控枚举 | 比较不同入口的行为与质量差异 |
| `request.locale` | O | BCP 47，例如 `zh-CN` | 解释语言相关检索、Prompt 和生成差异 |
| `request.query` | R | 用户当前问题原文 | RAG 运行、评测和 Bad Case 分析的核心输入 |
| `request.query_hash` | R | 规范化 query 的 SHA-256 | 支持精确重复统计、隐私化关联和数据完整性检查 |
| `request.conversation.conversation_id` | O | 稳定 ID | 关联同一多轮会话，但不把全部历史重复写入每个字段 |
| `request.conversation.turn_id` | O | 会话内唯一 ID | 定位当前轮次和顺序 |
| `request.conversation.history_ref` | C | 使用历史时必填 | 指向本次运行实际使用的不可变历史快照 |
| `request.conversation.history_hash` | C | 使用历史时必填 | 验证历史快照没有变化 |
| `request.metadata` | O | 白名单 JSON 对象 | 保存业务允许的切片标签，如客户端版本；禁止任意 PII 倾倒 |

### 4.3 运行版本 `versions`

| 字段路径 | 必要性 | 类型/约束 | 为什么存在 |
|---|---:|---|---|
| `versions.rag_config_version_id` | R | 不可变版本 ID | 一次性绑定完整 RAG 运行配置，是复现入口 |
| `versions.knowledge_base_id` | R | 稳定逻辑 ID | 支持按知识库聚合与权限判断 |
| `versions.index_version_id` | R | 不可变版本 ID | 解释召回差异并支持索引回滚比较 |
| `versions.retrieval_config_version_id` | R | 不可变版本 ID | 固定 top-k、过滤、query rewrite、融合和 rerank 策略 |
| `versions.embedding_model_config_version_id` | R | 不可变版本 ID | 解释向量空间和检索分数变化 |
| `versions.prompt_version_id` | R | 不可变版本 ID | 解释生成行为和支持 Prompt 实验 |
| `versions.generation_model_config_version_id` | R | 不可变版本 ID | 固定 provider、模型和默认参数 |
| `versions.code_version` | R | Git SHA/构建 ID | 区分相同配置在不同实现代码下的行为 |

`versions` 是本次运行承诺使用的配置快照；各阶段中的实际版本字段必须与它一致。若 provider 发生 fallback，需在 `model.fallback` 中显式记录实际变化。

### 4.4 检索信息 `retrieval`

| 字段路径 | 必要性 | 类型/约束 | 为什么存在 |
|---|---:|---|---|
| `retrieval.retrieval_run_id` | R | 全局唯一 ID | 允许一次 QueryRun 下定位具体检索阶段 |
| `retrieval.status` | R | `pending/running/succeeded/failed/skipped/cancelled/degraded` | 检索失败与生成失败需要分别诊断 |
| `retrieval.input_query` | R | 字符串 | 保留进入检索模块前的原始输入 |
| `retrieval.effective_queries[]` | R | 至少一个查询对象 | 记录实际执行的原 query、rewrite 或扩展 query |
| `effective_queries[].query_id` | R | 检索内唯一 ID | 将 hit 与产生它的具体 query 关联 |
| `effective_queries[].text` | R | 字符串 | 重放实际检索输入 |
| `effective_queries[].source` | R | `original/rewrite/expansion` | 解释 query 变换来源 |
| `effective_queries[].model_config_version_id` | C | LLM 改写时必填 | 固定 query rewrite 所用模型；规则改写可为 `null` |
| `retrieval.strategy` | R | `dense/sparse/hybrid` 等受控枚举 | 按检索策略切片并解释 score |
| `retrieval.top_k_requested` | R | 正整数 | 记录配置期望返回数量 |
| `retrieval.top_k_returned` | R | 非负整数 | 识别无召回、过滤过严和索引异常 |
| `retrieval.filters` | R | JSON 对象，可为空 | 重放 metadata/权限/时间过滤条件 |
| `retrieval.index_version_id` | R | 不可变版本 ID | 确认实际查询的索引，与 `versions` 交叉校验 |
| `retrieval.embedding_model_config_version_id` | R | 不可变版本 ID | 确认 query embedding 与索引空间兼容 |
| `retrieval.reranker_model_config_version_id` | O | 版本 ID 或 `null` | 解释 rerank 结果；未使用 rerank 时明确为空 |
| `retrieval.score_definition.raw_metric` | R | 如 `cosine_similarity` | 原始分数在不同 backend 间含义不同，必须声明 |
| `retrieval.score_definition.higher_is_better` | R | 布尔值 | 防止将 distance 与 similarity 反向解释 |
| `retrieval.score_definition.normalization` | R | 公式/策略标识 | 说明 `normalized_score` 如何产生，避免伪可比 |
| `retrieval.score_definition.calibration_version_id` | O | 版本 ID 或 `null` | 使用数据校准时绑定校准版本 |
| `retrieval.hits[]` | R | 有序数组，可为空 | 保存实际召回证据；空数组本身是重要质量事实 |
| `retrieval.error` | C | 失败/降级时为 Error 对象 | 保存机器可分析错误，不把错误文本混入 answer |

### 4.5 文档片段信息 `retrieval.hits[]`

| 字段路径 | 必要性 | 类型/约束 | 为什么存在 |
|---|---:|---|---|
| `hits[].hit_id` | R | Trace 内唯一 ID | Prompt、citation 和 evaluator 引用单次命中 |
| `hits[].matched_query_ids[]` | R | query ID 数组 | 解释 hybrid/multi-query 检索中命中来自哪个 query |
| `hits[].rank` | R | 从 1 开始 | 计算 Recall@K、MRR、nDCG 和位置偏差 |
| `hits[].chunk_id` | R | 稳定 ID | 关联知识库中的不可变证据单元 |
| `hits[].document_id` | R | 稳定逻辑 ID | 按文档聚合问题与权限 |
| `hits[].document_version_id` | R | 不可变版本 ID | 防止文档更新后历史证据漂移 |
| `hits[].chunk_set_version_id` | R | 不可变版本 ID | 解释 chunk 策略变化造成的差异 |
| `hits[].content` | C | 字符串或 `null` | 保存本次看到的精确文本；使用外部引用时可为空 |
| `hits[].content_ref` | C | 不可变对象引用或 `null` | 大文本外置时仍可读取完整证据；与 `content` 至少一个存在 |
| `hits[].content_hash` | R | SHA-256 | 验证证据内容，支持去重和重放一致性 |
| `hits[].token_count` | O | 非负整数 | 分析上下文预算和 chunk 大小影响 |
| `hits[].location.page_start/page_end` | O | 正整数或 `null` | PDF/分页文档的可解释引用 |
| `hits[].location.char_start/char_end` | O | 非负整数或 `null` | 精确定位源文档字符范围，end 为开区间 |
| `hits[].location.section_path[]` | O | 字符串数组 | 为用户和运营人员提供章节级溯源 |
| `hits[].source.uri` | O | 受控 URI | 指向原始来源，必须经过权限检查 |
| `hits[].source.title` | O | 字符串 | 提供人可读来源名称 |
| `hits[].source.mime_type` | O | MIME 字符串 | 解释解析方式与来源类型 |
| `hits[].raw_score` | R | 数值 | 保留 backend 原始排序事实 |
| `hits[].normalized_score` | O | 数值或 `null` | 同一校准规则下比较；无可靠规则时必须为 `null` |
| `hits[].rerank_score` | O | 数值或 `null` | 区分初召回与 rerank 影响 |
| `hits[].selected_for_context` | R | 布尔值 | 召回不等于进入 Prompt，用于诊断“有召回但未利用” |
| `hits[].context_order` | C | 入 Prompt 时为从 1 开始的整数 | 还原上下文拼接顺序和位置偏差 |
| `hits[].metadata` | O | 白名单 JSON 对象 | 保存语言、文档类别等切片标签，不承载核心字段 |

### 4.6 Prompt 信息 `prompt`

| 字段路径 | 必要性 | 类型/约束 | 为什么存在 |
|---|---:|---|---|
| `prompt.prompt_run_id` | R | 全局唯一 ID | 独立定位 Prompt 构造阶段 |
| `prompt.status` | R | 阶段状态枚举 | 区分 Prompt 构造错误和模型调用错误 |
| `prompt.prompt_version_id` | R | 不可变版本 ID | 关联模板与实验变体 |
| `prompt.template_hash` | R | SHA-256 | 防止版本引用与实际模板内容不一致 |
| `prompt.rendered_messages[]` | C | 生成阶段执行时必填 | 保存模型实际接收的 role/content，而不是只保存模板 |
| `rendered_messages[].role` | R | `system/user/assistant/tool` | 保留对话消息语义和顺序 |
| `rendered_messages[].content` | C | 字符串或 `null` | 内联模型实际输入；外置时可为空 |
| `rendered_messages[].content_hash` | R | SHA-256 | 验证每条消息的精确内容 |
| `prompt.rendered_messages_ref` | O | 不可变对象引用 | 大 Prompt 外置与受控访问 |
| `prompt.rendered_messages_hash` | R | 整体消息序列 SHA-256 | 快速判断两次运行的最终 Prompt 是否完全一致 |
| `prompt.variables` | R | 白名单 JSON 对象 | 保存模板变量和 question，解释渲染来源 |
| `prompt.context_hit_ids[]` | R | hit ID 数组，可为空 | 明确哪些检索片段进入了模型上下文 |
| `prompt.token_count` | O | 非负整数 | 分析上下文长度、截断和成本 |
| `prompt.truncation.applied` | R | 布尔值 | 识别因 token 预算导致的信息丢失 |
| `prompt.truncation.policy_version_id` | R | 不可变版本 ID | 固定截断算法和预算规则 |
| `prompt.truncation.dropped_hit_ids[]` | R | hit ID 数组 | 直接定位被丢弃的证据 |
| `prompt.redaction.applied` | R | 布尔值 | 说明发送模型前是否做脱敏 |
| `prompt.redaction.policy_version_id` | R | 不可变版本 ID | 解释脱敏行为并支持安全审计 |
| `prompt.redaction.fields[]` | R | 字段路径数组 | 记录哪些输入发生脱敏，不保存原敏感值 |
| `prompt.error` | C | 失败/降级时为 Error 对象 | 结构化记录 Prompt 构造失败 |

### 4.7 模型信息 `model`

| 字段路径 | 必要性 | 类型/约束 | 为什么存在 |
|---|---:|---|---|
| `model.model_config_version_id` | R | 不可变版本 ID | 绑定完整模型配置，支持实验与复现 |
| `model.provider` | R | 受控 provider 名称 | 区分服务商行为、成本和故障 |
| `model.model_name` | R | provider 模型标识 | 解释生成差异 |
| `model.endpoint_region` | O | 区域标识或 `null` | 数据驻留、延迟和合规分析 |
| `model.parameters.temperature` | R | 数值 | 影响随机性与输出稳定性 |
| `model.parameters.top_p` | R | 数值 | 固定采样策略 |
| `model.parameters.max_output_tokens` | R | 正整数 | 解释回答截断与成本 |
| `model.parameters.seed` | O | 整数或 `null` | provider 支持时提高可复现性；不保证完全确定 |
| `model.provider_request_id` | O | provider 返回 ID | 与供应商日志对账和故障排查 |
| `model.response_model_version` | O | provider 返回版本或 `null` | 捕获同名托管模型的实际后端版本漂移 |
| `model.fallback.used` | R | 布尔值 | 明确是否调用了非计划模型 |
| `model.fallback.from_model_config_version_id` | C | fallback 时必填 | 记录原计划模型配置 |
| `model.fallback.reason_code` | C | fallback 时必填 | 区分限流、超时、不可用等原因 |

### 4.8 生成结果 `generation`

| 字段路径 | 必要性 | 类型/约束 | 为什么存在 |
|---|---:|---|---|
| `generation.generation_run_id` | R | 全局唯一 ID | 独立定位生成阶段并关联 Feedback |
| `generation.status` | R | 阶段状态枚举 | 判断答案是否来自成功调用、降级或部分结果 |
| `generation.answer` | C | 成功/部分成功时为字符串 | 保存用户实际看到的最终答案 |
| `generation.answer_hash` | C | 有 answer 时必填 | 完整性校验、去重和实验差异检测 |
| `generation.finish_reason` | O | `stop/length/content_filter/error` 等 | 识别截断、安全过滤和非正常结束 |
| `generation.refusal.refused` | R | 布尔值 | 将有意拒答与生成失败区分开 |
| `generation.refusal.reason_code` | C | 拒答时必填 | 评测拒答是否正确，并按原因切片 |
| `generation.refusal.policy_version_id` | R | 版本 ID | 固定拒答规则，避免沿用不可解释的手工阈值 |
| `generation.citations[]` | R | 数组，可为空 | 显式连接回答主张与检索证据 |
| `citations[].citation_id` | R | 唯一 ID | 独立评测一条引用 |
| `citations[].hit_id` | R | 当前 Trace 的 hit ID | 确保引用来自实际召回内容 |
| `citations[].answer_span.start/end` | O | 字符索引，end 为开区间 | 将引用精确定位到答案片段 |
| `citations[].claim_text` | O | 字符串 | 提供人可读主张，并校验 span |
| `generation.usage.input_tokens` | O | 非负整数 | 成本、上下文长度和模型行为分析 |
| `generation.usage.output_tokens` | O | 非负整数 | 成本和回答长度分析 |
| `generation.usage.total_tokens` | O | 非负整数 | provider 对账和聚合 |
| `generation.error` | C | 失败/降级时为 Error 对象 | 保存机器可分析的生成错误 |

### 4.9 性能指标 `performance`

| 字段路径 | 必要性 | 类型/约束 | 为什么存在 |
|---|---:|---|---|
| `performance.total_latency_ms` | C | 终态必填，非负整数 | 端到端 SLO、实验和用户体验比较 |
| `performance.queue_ms` | O | 非负整数 | 区分资源排队与业务执行耗时 |
| `performance.retrieval_ms` | O | 非负整数 | 定位检索瓶颈 |
| `performance.rerank_ms` | O | 非负整数 | 衡量 rerank 的质量/延迟代价 |
| `performance.prompt_build_ms` | O | 非负整数 | 识别上下文拼接和脱敏开销 |
| `performance.generation_ms` | O | 非负整数 | 定位主要模型延迟 |
| `performance.time_to_first_token_ms` | O | 流式生成时使用 | 衡量用户感知响应速度 |
| `performance.trace_persist_ms` | O | 非负整数 | 评估 Trace 记录对在线链路的影响 |
| `performance.attempts.retrieval` | R | 正整数或 0 | 识别重试对延迟和稳定性的影响 |
| `performance.attempts.generation` | R | 正整数或 0 | 识别模型重试、限流和隐性成本 |
| `performance.cost.currency` | R | ISO 4217 | 防止不同币种直接相加 |
| `performance.cost.query_embedding` | O | 非负小数 | 单独核算 query embedding 成本 |
| `performance.cost.rerank` | O | 非负小数 | 衡量 rerank 成本收益 |
| `performance.cost.generation` | O | 非负小数 | 模型生成成本 |
| `performance.cost.total` | R | 非负小数 | 实验与项目级成本门禁 |

各阶段耗时可能因并行而不等于 `total_latency_ms`；不得用简单求和替代真实端到端计时。

### 4.10 用户反馈 `feedback[]`

| 字段路径 | 必要性 | 类型/约束 | 为什么存在 |
|---|---:|---|---|
| `feedback[]` | R | 数组，可为空 | 请求结束时可能没有反馈；后续以追加事实补充 |
| `feedback[].feedback_id` | R | 全局唯一 ID | 幂等写入和审计 |
| `feedback[].type` | R | `explicit_rating/thumb/correction/comment/implicit_action` 等 | 不把不同信号混为一个“满意度” |
| `feedback[].value` | R | 与 type 对应的版本化 JSON | 支持评分、布尔、纠正答案等不同结构 |
| `feedback[].actor_type` | R | `end_user/reviewer/system` | 区分用户意见、人工标签和系统行为 |
| `feedback[].source` | R | `web/api/import/review` 等 | 判断反馈采集渠道和可信度 |
| `feedback[].comment` | O | 字符串或 `null` | 保留可解释的定性反馈，需执行隐私治理 |
| `feedback[].created_at` | R | UTC ISO 8601 | 支持时序、延迟反馈和审计 |
| `feedback[].linked_generation_run_id` | R | generation run ID | 确保反馈对应用户实际看到的答案版本 |

人工 gold label 不应伪装成终端用户反馈；它可以使用 `actor_type=reviewer`，并在未来评测模型中进一步保存 rubric 与标注任务版本。

### 4.11 遥测关联与数据治理

| 字段路径 | 必要性 | 类型/约束 | 为什么存在 |
|---|---:|---|---|
| `observability.otel_trace_id` | O | OpenTelemetry Trace ID | 从业务质量事实跳转到系统 span |
| `observability.correlation_id` | O | 跨系统关联 ID | 对接外部 RAG 系统或网关排查 |
| `governance.data_classification` | R | 受控等级 | 决定访问、脱敏、导出和审计策略 |
| `governance.retention_policy_id` | R | 版本化策略 ID | 明确保存期限和删除规则 |
| `governance.redaction_policy_id` | R | 版本化策略 ID | 说明本次数据适用的脱敏规则 |
| `governance.content_storage` | R | `inline/reference/mixed` | 告诉消费者如何读取大文本字段 |

### 4.12 通用 Error 对象

`retrieval.error`、`prompt.error` 和 `generation.error` 使用同一逻辑结构：

| 字段 | 必要性 | 为什么存在 |
|---|---:|---|
| `stage` | R | 定位失败阶段 |
| `code` | R | 稳定机器错误码，用于聚合 |
| `message` | R | 脱敏后的人可读说明 |
| `retryable` | R | 指示是否允许自动重试 |
| `provider_request_id` | O | 与外部服务故障记录关联 |
| `details_ref` | O | 指向受控的详细诊断产物，不把堆栈或秘密直接写入 Trace |

成功阶段的 `error` 必须为 `null`；失败阶段必须提供 Error 对象。

## 5. 完整 JSON 示例

下面示例表示一次成功的线上知识库问答。哈希值为格式示例，不代表真实计算结果。

```json
{
  "schema_version": "1.0.0",
  "trace_id": "trc_01JZ8M4N7H4T6K2Q9A1B3C5D7E",
  "revision": 2,
  "workspace_id": "ws_demo",
  "project_id": "prj_support_qa",
  "environment": "staging",
  "status": "succeeded",
  "started_at": "2026-07-15T02:30:00.120Z",
  "ended_at": "2026-07-15T02:30:00.962Z",
  "recorded_at": "2026-07-15T02:30:00.976Z",
  "updated_at": "2026-07-15T02:31:18.000Z",
  "run_context": {
    "mode": "online",
    "parent_trace_id": null,
    "evaluation_run_id": null,
    "evaluation_case_id": null,
    "experiment_id": null,
    "variant_id": null,
    "pairing_key": null
  },
  "request": {
    "request_id": "req_01JZ8M4N5Z7P2M6V8X0C1B3A4D",
    "submitted_at": "2026-07-15T02:30:00.117Z",
    "session_id": "sess_8c8fb5",
    "user_ref": "usr_sha256_4ac9f0",
    "channel": "web",
    "locale": "zh-CN",
    "query": "退款审核通过后多久到账？",
    "query_hash": "sha256:ab31d4c3c3c1b2f9f61b7e5a9b1c4e0eab31d4c3c3c1b2f9f61b7e5a9b1c4e0e",
    "conversation": {
      "conversation_id": "conv_01JZ8M1Y",
      "turn_id": "turn_0007",
      "history_ref": "s3://ragops-traces/ws_demo/conv_01JZ8M1Y/turn_0007_history.json",
      "history_hash": "sha256:22a9f0e6b83a57f9c2f0d8c4e1a0b2c722a9f0e6b83a57f9c2f0d8c4e1a0b2c7"
    },
    "metadata": {
      "client_version": "web-0.1.0",
      "traffic_class": "internal_test"
    }
  },
  "versions": {
    "rag_config_version_id": "ragcfg_v17",
    "knowledge_base_id": "kb_customer_support",
    "index_version_id": "idx_v20260714_03",
    "retrieval_config_version_id": "retcfg_v8",
    "embedding_model_config_version_id": "embcfg_bge_m3_v2",
    "prompt_version_id": "prompt_qa_v11",
    "generation_model_config_version_id": "modelcfg_deepseek_chat_v4",
    "code_version": "git:6f4d7b8a2c91"
  },
  "retrieval": {
    "retrieval_run_id": "retr_01JZ8M4N",
    "status": "succeeded",
    "input_query": "退款审核通过后多久到账？",
    "effective_queries": [
      {
        "query_id": "qry_original",
        "text": "退款审核通过后多久到账？",
        "source": "original",
        "model_config_version_id": null
      }
    ],
    "strategy": "dense",
    "top_k_requested": 5,
    "top_k_returned": 2,
    "filters": {
      "document_status": "published",
      "language": "zh-CN"
    },
    "index_version_id": "idx_v20260714_03",
    "embedding_model_config_version_id": "embcfg_bge_m3_v2",
    "reranker_model_config_version_id": null,
    "score_definition": {
      "raw_metric": "cosine_similarity",
      "higher_is_better": true,
      "normalization": "(raw+1)/2",
      "calibration_version_id": null
    },
    "hits": [
      {
        "hit_id": "hit_01",
        "matched_query_ids": ["qry_original"],
        "rank": 1,
        "chunk_id": "chk_refund_policy_0042",
        "document_id": "doc_refund_policy",
        "document_version_id": "docver_refund_policy_v6",
        "chunk_set_version_id": "chunkset_v9",
        "content": "退款审核通过后通常在3到5个工作日内原路返回。",
        "content_ref": "s3://ragops-knowledge/kb_customer_support/docver_refund_policy_v6/chk_0042.json",
        "content_hash": "sha256:9447ce7a6fa8e4d1a3c5b2f09d7e113a9447ce7a6fa8e4d1a3c5b2f09d7e113a",
        "token_count": 23,
        "location": {
          "page_start": 3,
          "page_end": 3,
          "char_start": 128,
          "char_end": 153,
          "section_path": ["售后政策", "退款时效"]
        },
        "source": {
          "uri": "kb://customer-support/refund-policy",
          "title": "退款与原路退回说明",
          "mime_type": "application/pdf"
        },
        "raw_score": 0.82,
        "normalized_score": 0.91,
        "rerank_score": null,
        "selected_for_context": true,
        "context_order": 1,
        "metadata": {
          "language": "zh-CN",
          "document_type": "policy"
        }
      },
      {
        "hit_id": "hit_02",
        "matched_query_ids": ["qry_original"],
        "rank": 2,
        "chunk_id": "chk_refund_policy_0043",
        "document_id": "doc_refund_policy",
        "document_version_id": "docver_refund_policy_v6",
        "chunk_set_version_id": "chunkset_v9",
        "content": "对公付款的退款可能需要人工处理，到账时间以审核结果为准。",
        "content_ref": "s3://ragops-knowledge/kb_customer_support/docver_refund_policy_v6/chk_0043.json",
        "content_hash": "sha256:2d54a88f91b3e7496f62b431cb66810f2d54a88f91b3e7496f62b431cb66810f",
        "token_count": 28,
        "location": {
          "page_start": 3,
          "page_end": 3,
          "char_start": 154,
          "char_end": 184,
          "section_path": ["售后政策", "特殊付款方式"]
        },
        "source": {
          "uri": "kb://customer-support/refund-policy",
          "title": "退款与原路退回说明",
          "mime_type": "application/pdf"
        },
        "raw_score": 0.76,
        "normalized_score": 0.88,
        "rerank_score": null,
        "selected_for_context": true,
        "context_order": 2,
        "metadata": {
          "language": "zh-CN",
          "document_type": "policy"
        }
      }
    ],
    "error": null
  },
  "prompt": {
    "prompt_run_id": "prun_01JZ8M4P",
    "status": "succeeded",
    "prompt_version_id": "prompt_qa_v11",
    "template_hash": "sha256:48bf56f1e7a82cc810d3a7fbb21a02d948bf56f1e7a82cc810d3a7fbb21a02d9",
    "rendered_messages": [
      {
        "role": "system",
        "content": "你是知识库问答助手。仅依据给定证据回答，并明确特殊条件。",
        "content_hash": "sha256:57d8791a9bb4a12fbc8d014f55ea21c457d8791a9bb4a12fbc8d014f55ea21c4"
      },
      {
        "role": "user",
        "content": "证据1：退款审核通过后通常在3到5个工作日内原路返回。\n证据2：对公付款的退款可能需要人工处理，到账时间以审核结果为准。\n\n问题：退款审核通过后多久到账？",
        "content_hash": "sha256:eb8b111cadfb32057c0f392a9de8b6bdeb8b111cadfb32057c0f392a9de8b6bd"
      }
    ],
    "rendered_messages_ref": "s3://ragops-traces/ws_demo/trc_01JZ8M4N7H4T6K2Q9A1B3C5D7E/prompt.json",
    "rendered_messages_hash": "sha256:5f427f4f26d5248bbd3318781895fb195f427f4f26d5248bbd3318781895fb19",
    "variables": {
      "question": "退款审核通过后多久到账？"
    },
    "context_hit_ids": ["hit_01", "hit_02"],
    "token_count": 126,
    "truncation": {
      "applied": false,
      "policy_version_id": "truncation_v2",
      "dropped_hit_ids": []
    },
    "redaction": {
      "applied": false,
      "policy_version_id": "redaction_v3",
      "fields": []
    },
    "error": null
  },
  "model": {
    "model_config_version_id": "modelcfg_deepseek_chat_v4",
    "provider": "deepseek",
    "model_name": "deepseek-chat",
    "endpoint_region": "cn",
    "parameters": {
      "temperature": 0.2,
      "top_p": 1.0,
      "max_output_tokens": 512,
      "seed": null
    },
    "provider_request_id": "provider_req_dsk_74219",
    "response_model_version": null,
    "fallback": {
      "used": false,
      "from_model_config_version_id": null,
      "reason_code": null
    }
  },
  "generation": {
    "generation_run_id": "gen_01JZ8M4Q",
    "status": "succeeded",
    "answer": "退款审核通过后通常3到5个工作日原路返回；对公付款可能需要人工处理。",
    "answer_hash": "sha256:a1194af75d98c046f82d38c3eb0fa86ca1194af75d98c046f82d38c3eb0fa86c",
    "finish_reason": "stop",
    "refusal": {
      "refused": false,
      "reason_code": null,
      "policy_version_id": "refusal_v3"
    },
    "citations": [
      {
        "citation_id": "cit_01",
        "hit_id": "hit_01",
        "answer_span": {
          "start": 0,
          "end": 20
        },
        "claim_text": "退款审核通过后通常3到5个工作日原路返回"
      },
      {
        "citation_id": "cit_02",
        "hit_id": "hit_02",
        "answer_span": {
          "start": 21,
          "end": 33
        },
        "claim_text": "对公付款可能需要人工处理"
      }
    ],
    "usage": {
      "input_tokens": 126,
      "output_tokens": 32,
      "total_tokens": 158
    },
    "error": null
  },
  "performance": {
    "total_latency_ms": 842,
    "queue_ms": 3,
    "retrieval_ms": 41,
    "rerank_ms": 0,
    "prompt_build_ms": 7,
    "generation_ms": 760,
    "time_to_first_token_ms": 420,
    "trace_persist_ms": 14,
    "attempts": {
      "retrieval": 1,
      "generation": 1
    },
    "cost": {
      "currency": "CNY",
      "query_embedding": 0.0001,
      "rerank": 0.0,
      "generation": 0.0032,
      "total": 0.0033
    }
  },
  "feedback": [
    {
      "feedback_id": "fb_01JZ8M6W",
      "type": "explicit_rating",
      "value": {
        "rating": 4,
        "scale_min": 1,
        "scale_max": 5
      },
      "actor_type": "end_user",
      "source": "web",
      "comment": "回答清楚，但希望说明节假日是否顺延。",
      "created_at": "2026-07-15T02:31:18.000Z",
      "linked_generation_run_id": "gen_01JZ8M4Q"
    }
  ],
  "observability": {
    "otel_trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "correlation_id": "gw_req_91dc77"
  },
  "governance": {
    "data_classification": "confidential",
    "retention_policy_id": "retention_90d_v1",
    "redaction_policy_id": "redaction_v3",
    "content_storage": "mixed"
  }
}
```

## 6. 生命周期与一致性规则

### 6.1 Trace 生命周期

```text
pending → running → succeeded
                  ↘ partial
                  ↘ failed
                  ↘ cancelled
```

- `succeeded`：必须有成功 retrieval、prompt、generation 和 answer。
- `partial`：用户可能收到部分/降级结果，但至少一个必要阶段未完整成功。
- `failed`：没有形成可用答案；错误必须归属到具体阶段。
- `cancelled`：由用户或系统取消，不等同于失败。

### 6.2 可变与不可变部分

运行进入终态后，request、versions、retrieval、prompt、model、generation 和 performance 视为不可变事实。后续允许：

- 追加 Feedback。
- 修正治理信息或外部遥测关联。
- 生成更高 `revision` 的聚合快照。

禁止为了“修正结果”直接改写历史答案、hit 或版本；应创建新的 replay/experiment Trace，并用 `parent_trace_id` 关联。

### 6.3 引用完整性

- `prompt.context_hit_ids` 必须引用当前 `retrieval.hits[].hit_id`。
- `generation.citations[].hit_id` 必须同时存在于 hits，并且通常应已 `selected_for_context=true`。
- `context_order` 在被选中的 hit 中不得重复。
- `versions` 与阶段实际版本必须一致，fallback 除外且必须显式记录。
- `top_k_returned` 必须等于 `hits` 数量。
- token 和成本未知时使用 `null`，不得填 0 冒充真实观测；只有确认没有发生费用时才填 0。

### 6.4 时间与单位

- 时间统一使用 UTC ISO 8601，并保留毫秒。
- duration 统一使用整数毫秒，字段名以 `_ms` 结尾。
- token 统一使用 provider 返回或明确 tokenizer 计算的整数。
- 成本使用十进制数与 ISO 4217 币种；实现时避免二进制浮点累计误差。
- 字符 span 使用 Unicode code point 索引，start 包含、end 不包含；实现前需通过契约测试固定跨语言行为。

### 6.5 内容存储

- `inline`：内容直接在 Trace 中。
- `reference`：内容字段为 `null`，使用不可变 `*_ref` 与 hash。
- `mixed`：短内容内联，大内容同时或仅使用引用。

对象引用必须受 workspace 权限和保留策略约束；不能把带长期公开访问 token 的 URL 写入 Trace。

### 6.6 安全要求

- `user_ref` 不保存邮箱、手机号或外部明文用户 ID。
- query、Prompt、chunk、answer 和 comment 在写入前执行数据分类与脱敏。
- `metadata` 使用 schema 白名单，未知字段拒绝或隔离。
- Error 不保存 API Key、Authorization header、完整堆栈或原始敏感响应。
- 导出 Trace 时根据调用者权限裁剪正文、用户引用和对象地址。

## 7. 对未来能力的支持

### 7.1 支持 RAG 评测

#### 检索评测

- `chunk_id`、`document_version_id`、`rank` 支持 Recall@K、MRR、nDCG 和 Hit Rate。
- `top_k_returned=0` 可直接计算无召回率。
- `selected_for_context` 和 `context_order` 可区分“召回成功”与“最终上下文使用”。
- `score_definition` 防止不同向量库的 raw score 被错误横向比较。

#### 生成评测

- `query`、精确的 rendered Prompt、answer 和 hit content 支持 answer relevance、faithfulness 和完整性评测。
- citations 与 answer span 支持引用覆盖率和引用正确性。
- refusal 与 policy version 支持拒答正确性评测。

#### 系统评测

- 阶段状态与 Error 支持成功率、降级率和错误分布。
- performance 与 usage 支持延迟、token 和成本门禁。
- evaluator 结果应独立保存并引用 `trace_id`，这样更新 evaluator 后可重新评测历史 Trace。

### 7.2 支持 Bad Case 分析

Trace 可以在不使用固定单标签优先级的情况下，同时产生多个 Issue：

| Bad Case | Trace 证据示例 |
|---|---|
| 无召回 | `top_k_returned=0`，retrieval 成功但 hits 为空 |
| 检索失败 | `retrieval.status=failed` 与结构化 Error |
| 有召回但未利用 | hit 存在，但 `selected_for_context=false` 或未进入 Prompt |
| 上下文被截断 | `truncation.applied=true` 与 `dropped_hit_ids` |
| 疑似幻觉 | answer 主张缺少 citation，或与 hit content 冲突 |
| 答非所问 | query 与 answer 语义 evaluator 结果异常 |
| 错误拒答 | `refused=true`，但 gold evidence 足够 |
| 回答被截断 | `finish_reason=length` |
| 用户不满意 | 独立 Feedback 信号，不覆盖其他问题标签 |
| 性能问题 | 总耗时或具体阶段超过门限 |

Issue 应保存 evaluator 版本、证据路径（例如 `retrieval.hits[0]`）和严重程度，而不是把标签写回 Trace。一个 Trace 可以关联多个 Issue。

### 7.3 支持实验对比

实验中 baseline 和每个 variant 都产生独立 Trace：

- 使用相同 `evaluation_case_id` 和 `pairing_key` 保证成对比较。
- 使用不同 `variant_id` 与版本 ID 表示 Prompt、top-k、chunk、embedding、rerank 或模型变化。
- 对比 `retrieval.hits` 可解释召回变化。
- 对比 rendered Prompt 可确认变量是否真正生效。
- 对比 answer/MetricResult 可衡量质量变化。
- 对比 performance/cost 可报告质量提升的代价。
- `code_version` 可避免把实现变更误判为配置效果。

实验结论不写入 Trace；Experiment 和 ReleaseGateResult 引用参与比较的 trace IDs。这样原始事实保持不可变，门禁策略也可以独立版本化。

## 8. 从原型字段到 Trace Contract 的映射

| 原型字段/能力 | Trace Contract | 改进 |
|---|---|---|
| StudyRAG `query` | `request.query` | 增加 request/session/hash/locale |
| StudyRAG `retrieved_docs` | `retrieval.hits[]` | 增加文档版本、位置、rank、score 语义和上下文选择 |
| StudyRAG `scores` | `raw_score/normalized_score/rerank_score` | 分数含义显式化，不沿用固定阈值 |
| StudyRAG `answer` | `generation.answer` | 增加模型、Prompt、finish reason、citation 和 hash |
| StudyRAG `user_feedback` | `feedback[]` | 支持多条、多类型、来源、时间和 actor |
| SearchInsight 固定 CSV | Trace 聚合视图/导出 | 内部事实不再依赖 CSV 字符串嵌套 |
| SearchInsight 单标签 Bad Case | 独立多 Issue | 同一 Trace 可同时存在检索、生成和反馈问题 |
| SearchInsight Judge fallback | evaluator 独立状态 | fallback 不冒充正式 Judge 成功 |
| 两个原型固定文件产物 | 全局 ID + 不可变版本/引用 | 避免覆盖并支持重放、实验和审计 |

## 9. Sprint 1 后续确认项

在实现任何 schema、数据库或 API 前，还需评审：

1. MVP 是以内置 RAG runtime 产生 Trace，还是先接外部系统 Trace。
2. `schema_version=1.0.0` 的最小必填字段是否会给在线链路造成不可接受开销。
3. Prompt、chunk 和 answer 默认内联还是外置，以及各环境大小阈值。
4. Trace 核心事实采用同步保证、outbox 还是异步补偿。
5. 用户身份、query 和反馈的脱敏与保留规则。
6. 多轮历史的快照格式和 hash 规范。
7. query normalization、内容 hash、JSON canonicalization 和字符 span 的统一算法。
8. 失败、降级、重试和模型 fallback 的状态转换表。
9. 外部 RAG 系统无法提供全部字段时，采用拒绝、隔离还是兼容级别机制。

这些问题确认后，才能进入可执行 schema 与契约测试设计；当前文档不授权创建代码、数据库或接口。
