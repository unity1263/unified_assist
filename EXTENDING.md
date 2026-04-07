# Extending Unified Claw

这份文档说明后续如何在 `unified_assist` 里自己新增 `tool` 和 `skill`。

## 1. 新增 Tool

### 1.1 最简单的做法

把新工具放到：

- `src/unified_assist/tools/builtins/`

每个工具都基于 [BaseTool](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/tools/base.py)。

一个最小工具通常需要实现：

1. `name`
2. `description`
3. `input_schema()`
4. `parse_input()`
5. `call()`

可选但常用的还有：

1. `validate()`
2. `check_permission()`
3. `is_read_only()`
4. `is_concurrency_safe()`

### 1.2 基本模板

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult


@dataclass(slots=True)
class MyToolInput:
    value: str


class MyTool(BaseTool[MyToolInput]):
    name = "MyTool"
    description = "Do one focused thing"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
            },
            "required": ["value"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> MyToolInput:
        value = raw_input.get("value")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("value must be a non-empty string")
        return MyToolInput(value=value.strip())

    def is_read_only(self, parsed_input: MyToolInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: MyToolInput) -> bool:
        return True

    async def validate(self, parsed_input: MyToolInput, context: ToolContext) -> ValidationResult:
        return ValidationResult.success()

    async def call(self, parsed_input: MyToolInput, context: ToolContext) -> ToolResult:
        return ToolResult(content=f"handled: {parsed_input.value}")
```

### 1.3 注册工具

如果你希望它进入默认工具集，需要把它注册到：

- [builtin_tools()](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/tools/builtins/__init__.py)

也可以只在自定义 runner 里注册：

```python
from unified_assist.tools.registry import ToolRegistry
from unified_assist.tools.builtins.my_tool import MyTool

registry = ToolRegistry()
registry.register(MyTool())
```

MiniMax runner 默认走：

- [build_builtin_tool_registry()](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/app/minimax_runner.py)

### 1.4 Tool 能访问什么上下文

工具运行时能从 [ToolContext](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/tools/base.py) 读取：

- `cwd`: 当前工作目录
- `permission_mode`: 当前权限模式
- `metadata`: 运行时附加信息

目前常见的 `metadata` 内容包括：

- `runtime_services`
- `tool_registry`
- `skill_catalog`
- `messages`
- `invoked_skills`
- `todos`

如果工具需要把信息写回后续轮次，返回：

```python
ToolResult(
    content="done",
    metadata={
        "context_patch": {
            "some_key": "some_value"
        }
    },
)
```

`ToolExecutor` 会把这个 patch 合并回当前上下文。

### 1.5 Tool 命名建议

如果是 Claude Code 兼容工具，名字要和模型看到的一致，比如：

- `Read`
- `Edit`
- `Bash`
- `Skill`
- `TodoWrite`

如果是内部或 Python 风格工具，也可以保留蛇形命名，比如：

- `read_file`
- `write_file`
- `spawn_agent`

现在仓库里两套命名都支持。兼容命名示例可以看：

- [compat_fs.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/tools/builtins/compat_fs.py)
- [compat_interaction.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/tools/builtins/compat_interaction.py)

### 1.6 Tool 测试建议

推荐按这两层写：

1. 工具本身的行为测试
2. 注册或 loop 集成测试

可以参考：

- [test_tool_port.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/tests/test_tool_port.py)
- [test_tools_foundation.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/tests/test_tools_foundation.py)
- [test_web_and_lsp.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/tests/test_web_and_lsp.py)

测试原则：

- 不要依赖真实外网
- 优先注入 fake transport/provider
- 只测这个工具负责的行为

## 2. 新增 Skill

### 2.1 最简单的做法：写本地 SKILL.md

最推荐的方式是在工作区直接新建：

- `skills/<skill-name>/SKILL.md`

加载逻辑在：

- [load_all_skills()](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/skills/loader.py)
- [load_skills_dir()](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/skills/loader.py)

一个最小示例：

```markdown
---
name: api-review
description: Review API changes carefully
when_to_use: Use when the user asks for an API review or backend contract review.
allowed_tools:
  - Read
  - Grep
  - Glob
context: inline
paths:
  - src/**/*.py
auto_activate: true
---

# API Review

## Goal
Review API-facing changes and catch contract, validation, and compatibility issues.

## Steps
1. Read the changed API handlers and schemas.
2. Search for all call sites and shared types.
3. Verify request/response compatibility and validation paths.
4. Summarize risks and missing tests.
```

### 2.2 Frontmatter 字段说明

常用字段：

- `name`: skill 名称
- `description`: 简短描述
- `when_to_use`: 什么时候用
- `allowed_tools`: 这个 skill 偏好的工具名
- `context`: `inline` 或 `fork`
- `paths`: 路径匹配规则
- `hooks`: 生命周期 hook
- `auto_activate`: 是否允许按路径自动激活

注意：

- `allowed_tools` 要写“模型看到的工具名”，比如 `Read`、`Edit`、`Bash`
- 如果你想让 skill 只在显式调用 `Skill` 工具时生效，设 `auto_activate: false`
- 同名本地 skill 会覆盖 bundled skill

### 2.3 新增 bundled skill

如果你希望这个 skill 跟程序一起发布，而不是只存在某个工作区，就把它加到：

- [bundled.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/skills/bundled.py)

当前 bundled skill 的组织方式是：

1. 在 `load_bundled_skills()` 中追加一个 `Skill(...)`
2. 默认设置 `auto_activate=False`
3. 让它通过 `Skill` 工具显式调用，或者以后再加更复杂的激活策略

### 2.4 Skill 在运行时怎么生效

主链路在：

- [resolver.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/skills/resolver.py)
- [agent_loop.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/loop/agent_loop.py)
- [prompt/builder.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/prompt/builder.py)

流程是：

1. 先加载 bundled + workspace skills
2. 根据 `paths` 和 `invoked_skills` 解析 active skills
3. 把 skill 内容渲染进 prompt
4. 如果有 hook，再接到 tool lifecycle 上

### 2.5 Skill 测试建议

可以参考：

- [test_skills.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/tests/test_skills.py)
- [test_prompt.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/tests/test_prompt.py)

建议至少测：

1. frontmatter 是否被正确读取
2. path matching 是否符合预期
3. prompt 注入是否生效
4. 如果有 hook，hook 是否真的触发

## 3. 常见扩展入口

你后续最常改的地方通常就是这些：

- 工具基类与协议：
  [tools/base.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/tools/base.py)
- 默认工具注册：
  [tools/builtins/__init__.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/tools/builtins/__init__.py)
- skill 加载：
  [skills/loader.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/skills/loader.py)
- bundled skills：
  [skills/bundled.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/skills/bundled.py)
- 运行入口：
  [app/minimax_runner.py](/home/dehuazhang12/codebase/claude-code-source/unified_assist/src/unified_assist/app/minimax_runner.py)

## 4. 开发完成后怎么验证

全量测试：

```bash
python3 -m unittest discover -s unified_assist/tests -t unified_assist -v
```

只跑某个测试文件：

```bash
cd unified_assist
python3 -m unittest tests.test_tool_port -v
python3 -m unittest tests.test_skills -v
```

## 5. 推荐的扩展顺序

如果你后面自己继续扩：

1. 先写独立工具
2. 再接入 `builtin_tools()` 或自定义 runner
3. 再写 skill 把这个工具编排进去
4. 最后补 loop/prompt 集成测试

这样最稳，也最容易定位问题。
