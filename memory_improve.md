：这个 memory 不是向量库，也不是程序强管控的数据库，而是一个“以 repo 为命名空间、由模型自己读写 Markdown 文件”的长期记忆系统；MEMORY.md 是索引，主题 memory 文件是正文，查询时再按相关性把少量正文作为 attachment 注入当前轮。memdir.ts (line 34) memoryTypes.ts (line 14)

实现概览

持久化根目录默认在 ~/.claude/projects/<sanitized-git-root>/memory/，并且按 canonical git root 做 namespace，所以同一个 repo 的 worktree 共享记忆；也支持受信任的 env/settings 覆盖路径。paths.ts (line 85) paths.ts (line 223)
记忆正文是“一个 memory 一个 .md 文件”，推荐 frontmatter 只有 name / description / type 三个字段，type 被限制为 user / feedback / project / reference 四类；但这是“软约束”，写入主要靠 prompt 约束，代码侧只是在读取时尽量解析，缺字段或未知 type 也会降级处理，不会硬失败。memoryTypes.ts (line 23) memoryTypes.ts (line 261)
MEMORY.md 不是正文，而是索引；每行一个 topic pointer，要求短、语义化、非时间流水账。代码对它做了硬截断：最多 200 行、25KB，超了会只加载前半并追加 warning。memdir.ts (line 35) memdir.ts (line 57)
记忆不会替代 CLAUDE.md 体系。CLAUDE.md/.claude/rules 更像“指令层”，auto-memory/team-memory 更像“跨会话事实层”；最终两者都通过 getMemoryFiles() 汇入上下文。claudemd.ts (line 790) claudemd.ts (line 1153)
保存与维护

主模型本身就能直接写 memory，因为系统 prompt 会教它怎么保存/更新/删除；如果主模型这一轮没写，turn 结束后 extractMemories 会起一个 forked subagent，从最近消息里抽取 durable memory 并落盘。memdir.ts (line 199) extractMemories.ts (line 329)
这个 extraction agent 被严格限权：只能读、grep、glob、只读 bash，以及仅在 memory 目录内 edit/write；所以它本质上是“受限的 memory maintainer”。extractMemories.ts (line 171)
extraction 还会先扫描现有 memory frontmatter，生成 manifest，优先更新已有 topic file 而不是重复创建。memoryScan.ts (line 35) extractMemories.ts (line 395)
更高层还有 autoDream：按默认 24h + 至少5个 session 触发，做一次“反思式 consolidation”，把近期信息合并、去重、修正漂移、裁剪索引。这才是它真正的“压缩/蒸馏”机制。autoDream.ts (line 63) consolidationPrompt.ts (line 10)
在 KAIROS/assistant 模式下，新记忆不是直接维护 MEMORY.md，而是先 append 到 logs/YYYY/MM/YYYY-MM-DD.md 的日记文件，再由 nightly /dream 蒸馏成 topic files + MEMORY.md；这是一种“日志层 -> 语义层”的双层设计。memdir.ts (line 318) paths.ts (line 237)
检索方式

平时注入上下文的不是所有 memory 正文，而主要是 MEMORY.md 索引；具体正文只在需要时再召回。这就是它控制 token 的核心思路。claudemd.ts (line 979) claudemd.ts (line 1142)
新版召回不是 embedding 检索，而是“先扫 frontmatter，再让 sideQuery 选”。具体做法是：递归扫描 memory 目录里最多 200 个 .md，只读前 30 行 frontmatter，拿到 filename / description / type / mtime，然后用一个 Sonnet side query 从 manifest 里挑最多 5 个相关文件。memoryScan.ts (line 21) findRelevantMemories.ts (line 39)
所以它更像“弱结构化 RAG”：检索依据主要是文件名和 description，不是全文 embedding。这很轻量，但召回质量很依赖描述写得好不好。
召回结果会作为 relevant_memories attachment 注入，而不是塞回 system prompt；每个文件最多取 200 行、4KB，整场会话累计最多 60KB，并会去重，避免同一个 memory 反复出现。attachments.ts (line 269) attachments.ts (line 2279) attachments.ts (line 2520)
召回是异步 prefetch 的，跟主轮模型流式输出并行；如果没及时准备好，这一轮就跳过，不阻塞主链路。query.ts (line 301) query.ts (line 1592)
系统对 stale memory 很敏感：超过 1 天就会附加 freshness note，prompt 里也明确要求“memory 只是当时为真，当前回答前要去代码/资源验证”。这和 coding tool 的场景非常契合。memoryAge.ts (line 33) memoryTypes.ts (line 201)
隔离性

最底层隔离单位是 repo。auto-memory 按 git root 分桶，不同项目天然隔离；worktree 共享同一桶，这对 coding assistant 很合理。paths.ts (line 198)
team memory 是 auto-memory 下的 team/ 子目录，既共享又隔离于 private memory；prompt 层也会告诉模型何时写 private、何时写 team。teamMemPrompts.ts (line 22)
team memory 的路径校验做得很严：防 ..、防 URL 编码绕过、防 Unicode 归一化穿越、防绝对路径、防 symlink escape，写入前会 realpath 校验 containment。teamMemPaths.ts (line 22) teamMemPaths.ts (line 228)
team sync 也是 repo-scoped 的，按 git remote 对应的 repo slug 同步；pull 是 server-wins per key，push 是 checksum delta upload，冲突时同 key 以本地编辑为准；删除本地文件不会删除服务端，下次 pull 还会回来。teamMemorySync.ts (line 1) teamMemorySync.ts (line 869)
team sync 还会做 secret scan，发现像凭证这类内容就直接跳过上传；这说明它把“共享记忆”当成潜在泄露面来设计。teamMemorySync.ts (line 557)
还有一层是 agent memory。不同 agent 可有独立的 user/project/local 作用域；如果用户在输入里 @ 某个 agent，相关记忆检索只搜该 agent 的 memory dir，不搜全局 auto-memory。agentMemory.ts (line 12) attachments.ts (line 2196)
我认为它当前最“coding-tool 化”的地方

taxonomy 只有 user / feedback / project / reference 四类，而且明确排除了代码结构、git 历史、调试方案，因为这些都应该从 repo 当前状态推导出来。memoryTypes.ts (line 183)
记忆的 namespace、同步边界、验证策略，几乎都围绕“项目目录 / git repo / 代码是否还存在”展开。
检索时还会根据“最近用过哪些工具”抑制某些工具文档类记忆，这是典型 coding-agent 优化，不适合通用个人助手。findRelevantMemories.ts (line 18)
如果改造成“个人助手”

最小改法是保留“文件系统 + 索引 + dream”的骨架，但把 namespace 从 repo 改成 person / household / workspace / domain，例如 profile/, people/, routines/, calendar/, health/, finance/, travel/，而不是绑在 git root 上。
type 也要改成更贴近人类生活的 schema，比如 identity / preference / person / routine / event / plan / commitment / reference / sensitive，并在 frontmatter 里增加 source / confidence / sensitivity / last_verified_at / ttl / entities / date_range。现在的 name/description/type 太弱。
检索要从“文件名+description LLM 选 top5”升级成“结构化过滤 + 语义检索 + 时间/人物/地点触发”。个人助手很多查询是“上周和张三聊过什么”“我妈对餐馆有什么忌口”，只靠 frontmatter 很难稳。
验证策略要从“去 grep 代码”改成“去日历、通讯录、邮件、IM、笔记、地图、设备状态”等 source of truth；而且 memory 里必须带 provenance，不然很容易把旧偏好、旧计划当成事实。
压缩要做成三层：原始日志、情节记忆（episodic）、稳定事实/偏好（semantic）。现在的 dream 已经有这个方向，但还太 repo-oriented；个人助手更需要周/月总结、关系演化、习惯提炼、过期计划淘汰。
隐私模型要重做。现在 team memory 的“本地删不掉云端、下次 pull 会回来”对代码知识库还能接受，对个人助手几乎不行；必须支持真正删除、tombstone、端到端加密、敏感字段单独授权。
共享语义也要变。现在的 team memory 是“同 repo 组织成员共享”；个人助手更像“家庭共享、项目共享、和某个同事共享某个空间”，共享范围不能绑定 repo slug。
交互上建议保留 /memory 这种可审计入口，但增加“为什么记住这个”“忘掉这条”“把这条从临时记忆提升为长期偏好/联系人事实”的操作，不然个人场景下用户很难建立信任。
