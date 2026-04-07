# Memory Implementation Notes

## 1. Overview

`unified_assist` 现在的 "memory" 其实分成三层，它们职责不同：

| Layer | Purpose | Persistence medium | Isolation granularity |
| --- | --- | --- | --- |
| Durable memory | 保存用户偏好、项目背景、协作反馈等长期信息 | `.assist/memory/**/*.md` | workspace 级 |
| Session transcript | 保存会话历史，支持 resume / recovery | `.assist/transcripts/<session_id>.jsonl` | session 级 |
| Context compaction | 缩短当前 prompt，避免上下文过长 | 内存中的 summary message | 单次运行 / 当前会话状态 |

代码入口主要在：

- `src/unified_assist/memory/store.py`
- `src/unified_assist/memory/manager.py`
- `src/unified_assist/memory/recall.py`
- `src/unified_assist/memory/consolidator.py`
- `src/unified_assist/stability/transcript_store.py`
- `src/unified_assist/stability/compaction.py`
- `src/unified_assist/stability/resume.py`

## 2. Persistent storage model

### 2.1 Directory layout

应用根目录由 `AppConfig.root_dir` 决定，数据目录固定放在：

```text
<workspace>/
  .assist/
    memory/
      MEMORY.md
      user/
      feedback/
      project/
      reference/
    transcripts/
      <session_id>.jsonl
    tool_results/
```

这里有两个重要结论：

- 长期 memory 是 workspace 共享的，不按 `session_id` 隔离。
- transcript 是按 `session_id` 隔离的，一个 session 对应一个 JSONL 文件。

### 2.2 Durable memory save format

长期 memory 使用 Markdown 文件加 YAML frontmatter 保存，每条记录对应一个独立文件。

示例结构：

```markdown
---
name: release-window
description: Release next week
type: project
updated_at: 2026-04-06T12:34:56+00:00
---
The release is next week.
```

关键点：

- `type` 目前固定支持 `user`、`feedback`、`project`、`reference`
- `updated_at` 使用 ISO8601 时间字符串
- 正文部分直接是纯文本 Markdown 内容
- 文件名由 `slugify(name)` 生成，默认是小写、非字母数字转 `-`

实现上是简单的 `write_text()` 覆盖写入，因此：

- 同一个 `kind + slug` 会直接覆盖旧文件
- 没有版本历史
- 没有 append log
- 没有原子 rename / fsync 之类的强一致保障

### 2.3 Transcript save format

会话历史不是按整份快照覆盖保存，而是采用 append-only JSONL。

记录类型有三种：

- `pending_turn`: 用户消息已接受，但模型回合还没完成
- `commit_turn`: 某个 pending turn 对应的 assistant/tool 结果已完成
- `cancel_turn`: pending turn 被取消

这个设计的优点是：

- 可以先落盘用户输入，再开始真正生成
- 进程中断后可以恢复到 "最后一个稳定状态"
- 不需要整份 transcript 重写

## 3. Isolation model

## 3.1 Workspace isolation

长期 memory 完全绑定在 `root_dir/.assist/memory` 下，因此天然按 workspace 隔离：

- 不同项目目录有不同 memory
- 同一个项目下的所有 session 共享同一份长期 memory

这意味着长期 memory 更像 "项目知识库"，而不是 "单次对话私有状态"。

## 3.2 Session isolation

`TranscriptStore` 用 `session_id` 区分不同会话：

- `session-a` -> `.assist/transcripts/session-a.jsonl`
- `session-b` -> `.assist/transcripts/session-b.jsonl`

所以会话级历史、pending turn、resume 都是 session 私有的。

## 3.3 Turn-local isolation

工具执行时，`ToolContext.snapshot()` 会拷贝一份 metadata，形成当前 turn 的执行视图。工具如果返回 `context_patch`，才会被显式 merge 回主上下文。

这意味着：

- 当前轮工具看到的是快照，不直接共享可变对象引用语义
- 上下文变化需要显式合并
- 这是执行上下文隔离，不是磁盘持久化隔离

## 3.4 What is not isolated yet

当前实现还没有这些能力：

- 多进程文件锁
- 并发写冲突检测
- 乐观锁 / CAS
- per-user memory namespace
- memory ACL / 权限隔离
- 加密存储

所以如果多个进程同时改同一条 memory，实际行为基本是 last write wins。

## 4. Read and recall path

### 4.1 Loading

`MemoryStore.list_entries()` 会扫描四类目录下的 `*.md` 文件并逐个解析 frontmatter。

`updated_at` 的读取优先级是：

1. frontmatter 中的 `updated_at`
2. 文件 `mtime`

### 4.2 Recall algorithm

当前 recall 不是向量检索，而是非常轻量的词项重叠打分：

1. 对 query 分词
2. 对 `name + description + content` 分词
3. 统计词项 overlap
4. 加一个 recency bonus: `1 / (1 + age_days(updated_at))`

最终按分数倒序取 top-k，默认 `limit=5`。

这带来几个明显特征：

- 实现简单，可解释
- 不依赖外部索引或 embedding 服务
- 对精确关键词很有效
- 对语义近义表达、长文本理解、跨语言召回比较弱

### 4.3 Freshness handling

召回结果会带两个 freshness 字段：

- `freshness`: `today` / `yesterday` / `N days old`
- `freshness_note`: 当记录超过 1 天时，提示先验证再信任

这不是硬性校验，而是 prompt 层的风险提示。

### 4.4 Prompt injection

每轮 `AgentLoop` 会：

1. 取最后一个用户 query
2. 召回相关 memory
3. 通过 `PromptBuilder` 注入到 system prompt

注入内容包含：

- memory 类型
- 名称
- 描述或摘录
- freshness
- 原始文件路径
- freshness note

因此 memory 当前主要用于 "给模型看"，不是运行时强规则系统。

## 5. Save and lifecycle behavior

### 5.1 Durable memory

`MemoryManager.prepare()` 只负责建目录结构，不会自动写入 memory。

当前 runtime 里并没有完整的 "自动判定哪些对话内容应该存入长期记忆" 流程。也就是说：

- 长期 memory 的读路径已经接好
- 长期 memory 的底层写接口也已经有了
- 但自动保存策略还没有真正落到主运行链路里

这点很重要：现在的 memory 更像 "ready-to-use storage layer"，还不是一个自动成长的 memory system。

### 5.2 Transcript lifecycle

会话提交流程是：

1. `SessionEngine.submit()` 先把用户消息写成 `pending_turn`
2. 再启动 agent loop
3. 如果成功完成，则写 `commit_turn`
4. 如果启动失败，则写 `cancel_turn`

`resume()` 时会：

1. 读取 transcript
2. 找出 pending turn
3. 清理未闭合的 assistant tool calls
4. 补一条 system resume note
5. 必要时再补一条 meta user message，要求从稳定状态继续

这套机制保证的是：

- "接受到的用户输入" 不容易丢
- 中断后可以继续
- unfinished tool call 不会被当作有效状态继续信任

## 6. Compression and compaction

## 6.1 Durable memory itself is not compressed

长期 memory 当前没有真正的压缩机制：

- 不会自动合并多条 memory
- 不会自动摘要旧记录
- 不会按大小做归档
- 不会做增量版本压缩

唯一接近 "整理" 的能力是 `rebuild_memory_index()`，它会扫描所有记录并重建一个 `MEMORY.md` 索引页。但这个索引只是导航页，不是压缩后的 canonical store。

## 6.2 Conversation compaction is separate

为了防止 prompt 过长，`AgentLoop` 在每轮开始前会对 `state.messages` 做 `compact_messages()`：

- 如果消息数没有超阈值，原样保留
- 如果超阈值，保留尾部若干条消息
- 把前面的消息压成：
  - 一个 `AttachmentMessage(kind="compaction_boundary")`
  - 一个 `SystemMessage("Previous conversation summary: ...")`

默认参数：

- `max_messages=12`
- `preserve_tail=4`

当模型返回 `prompt too long` 这类错误时，还会触发更激进的 reactive compaction：

- `max_messages` 改成更小
- `preserve_tail=2`

## 6.3 Compaction characteristics

这套压缩是典型的 lossy compaction：

- 保留高层摘要
- 丢掉精确的旧消息正文
- 目标是继续完成任务，不是完整归档

因此它更像 "短期上下文预算控制"，不是长期 memory 的整理机制。

## 7. Current strengths

- 全部基于本地文件，结构透明，便于调试
- 长期 memory 与 session transcript 分层清晰
- transcript 是 append-only，恢复语义明确
- recall 成本低，不依赖外部服务
- freshness 提示能降低旧记忆误导风险
- context compaction 已经接入主循环，可实际缓解 prompt overflow

## 8. Current limitations

- 长期 memory 还没有自动写入链路
- 没有语义检索，只有关键词 overlap
- 没有真正的 memory consolidation / summarization pipeline
- `MEMORY.md` 索引不会在每次写入后自动刷新
- 文件写入不是原子事务
- 没有并发冲突控制
- 没有加密、审计、保留策略
- memory 是 workspace 共享的，不是 session 私有的

## 9. Practical summary

如果用一句话总结当前实现：

> `unified_assist` 已经具备一个可工作的、文件驱动的 memory substrate，但它更偏向 "可持久化的知识底座 + 可恢复的会话日志 + 运行时上下文压缩"，还不是一个 fully automatic 的长期记忆系统。

如果后面要继续增强，最自然的演进方向通常是：

1. 接入自动 memory 写入策略
2. 给长期 memory 增加 consolidation / dedupe
3. 引入更强的 recall 排序或语义检索
4. 给文件写入增加并发与原子性保障
