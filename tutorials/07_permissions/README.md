# Tutorial 07: Permission 系统 — 控制 Agent 的行为边界

> **什么时候需要这个？** Agent 能跑 Bash、写文件之后，你必须给它划一条"什么能做、什么得问一下、什么绝对不能做"的红线——尤其是要把它跑在线上环境、共享环境或无人值守的定时任务里。

## 本章基于前序章节

- **T03 — `ToolBase.is_read_only` / `check_permissions`**：权限系统在 T03 的工具基类之上构建判定逻辑。
- **T04–T06 — Toolkit / MCP / Skill**：权限规则同样作用于工具组、MCP 工具和 Skill 触发的操作。

## 你将学到

- 权限系统的三类决策来源：规则、模式策略、工具自身判定
- 五种 `PermissionMode` 的行为差异
- `PermissionRule` 的工具特定匹配语法
- 如何配置 Allow / Deny / Ask 规则
- 不同模式的决策顺序，以及 BYPASS 的真实边界

## 前置要求

- 完成 Tutorial 06
- 理解 ToolBase 的 `is_read_only` 和 `check_permissions` 概念

## 核心概念

### 为什么需要权限系统？

Agent 具有工具调用能力后，就可以执行文件操作、Shell 命令等有风险的操作。权限系统在 Agent 和工具之间建立了一道安全屏障，确保：

- 只读场景下不会误修改文件
- 危险命令需要用户确认
- 无人值守时不会卡在等待确认

### 五种 PermissionMode

```python
from agentscope.permission import PermissionMode

# 每种模式适用不同场景
PermissionMode.DEFAULT       # 默认 ASK；工具明确 ALLOW 时可直接执行
PermissionMode.ACCEPT_EDITS  # 工作目录内的文件编辑自动允许
PermissionMode.EXPLORE       # 只读模式：只允许读取，禁止写入
PermissionMode.BYPASS        # 跳过 ASK；仅保留显式规则和工具 DENY
PermissionMode.DONT_ASK      # 不询问，直接拒绝 ASK 类决策
```

| 模式 | 读取 | 写入 | Bash | 适用场景 |
|------|------|------|------|----------|
| DEFAULT | 通常 ASK | 通常 ASK | 已识别只读命令可 ALLOW | 默认交互 |
| ACCEPT_EDITS | ALLOW | 工作目录内 ALLOW* | 依命令和路径判定 | 开发迭代 |
| EXPLORE | ALLOW | DENY | 只读命令 ALLOW，其余 DENY | 浏览代码 |
| BYPASS | 通常 ALLOW | 通常 ALLOW | 通常 ALLOW | 可信沙箱 |
| DONT_ASK | ALLOW 保留，ASK→DENY | ALLOW 保留，ASK→DENY | ALLOW 保留，ASK→DENY | 定时任务 |

\* ACCEPT_EDITS 的写入自动允许仅限于工作目录内

> BYPASS 不是“无条件 ALLOW”。用户配置的 DENY / ASK 规则，以及工具自身明确返回的 DENY，仍然生效；但工具返回的安全 ASK 会被跳过，所以只应在隔离且可信的环境中使用。

### PermissionRule

规则由四个字段组成：

```python
from agentscope.permission import PermissionRule, PermissionBehavior

rule = PermissionRule(
    tool_name="Bash",                    # 规则作用的工具名
    rule_content="python",               # Bash 使用命令子串匹配
    behavior=PermissionBehavior.ALLOW,   # ALLOW / DENY / ASK
    source="tutorial",                   # 规则来源标识
)
```

不同工具的 `rule_content` 匹配语法不同：

| 工具 | 匹配方式 | 示例 |
|------|----------|------|
| Bash | 命令子串匹配 | `"python"` 匹配 `python script.py` |
| Read / Write / Edit | glob 路径匹配 | `"src/**"` 匹配 `src/main.py` |
| 其他工具 | 通用模式匹配 | 取决于工具实现 |

空 `rule_content` 匹配所有调用。

### 决策优先级

权限引擎不是所有模式共用一条完全相同的流水线。共同起点是先检查用户配置的 DENY、ASK 规则，然后由当前模式决定后续行为：

```
DENY 规则 → ASK 规则 → 当前模式策略 / 工具 check_permissions
                              ↓
                         Allow 规则（适用时）
                              ↓
                         当前模式的默认结果
```

- `DEFAULT`：工具明确 ALLOW / DENY 就采用；安全 ASK 不会被 Allow 规则覆盖；否则匹配 Allow 规则，最后默认 ASK。
- `EXPLORE`：直接以本次调用是否只读为准，只读 ALLOW、修改 DENY；Allow 规则不能突破只读边界。
- `ACCEPT_EDITS`：只读调用和工作目录内编辑可自动 ALLOW，其他调用继续走工具判定、Allow 规则和默认 ASK。
- `BYPASS`：显式 DENY / ASK 规则和工具 DENY 仍生效；工具 ASK 被跳过，最后默认 ALLOW。
- `DONT_ASK`：任何原本要 ASK 的分支都转成 DENY，保证无人值守时不会挂起等待。

### PermissionContext

```python
from agentscope.permission import PermissionContext, PermissionMode, PermissionRule

context = PermissionContext(
    mode=PermissionMode.DEFAULT,
    allow_rules={
        "Bash": [
            PermissionRule(
                tool_name="Bash",
                rule_content="python",
                behavior=PermissionBehavior.ALLOW,
                source="tutorial",
            ),
        ],
    },
    deny_rules={
        "Bash": [
            PermissionRule(
                tool_name="Bash",
                rule_content="rm -rf",
                behavior=PermissionBehavior.DENY,
                source="tutorial",
            ),
        ],
    },
)
```

### 将权限配置装入 Agent

`PermissionContext` 本身只是一份配置——它需要通过 `AgentState` 传入 `Agent` 构造函数才能生效：

```python
from agentscope.agent import Agent
from agentscope.state import AgentState

agent = Agent(
    name="DataMuse",
    system_prompt="...",
    model=model,
    toolkit=toolkit,
    # ← 权限在这里注入：通过 state 参数
    state=AgentState(permission_context=context),
)
```

关键点：

- **`state=AgentState(permission_context=...)`** 是唯一的注入点。不传 `state` 参数时，Agent 使用默认 `AgentState()`，其中 `permission_context` 的模式为 `DEFAULT`（所有操作 ASK）。
- `PermissionContext` 对象在 Agent 生命周期内可以**运行时修改**——例如 `agent.state.permission_context.mode = PermissionMode.BYPASS` 可以在调试时临时放开限制。
- 同一个 `PermissionContext` 实例可以**跨多个 Agent 共享**（如果你想让一组 Agent 共用同一套规则），也可以每个 Agent 独立配置。

## 示例：为 DataMuse 配置不同权限级别

本期通过四个示例展示权限系统的工作方式：

1. **EXPLORE 模式**：只读浏览，禁止一切修改
2. **ACCEPT_EDITS 模式**：允许写入工作目录
3. **规则配置**：Allow + Deny 规则的精细控制
4. **DONT_ASK 模式**：无人值守的安全降级

## 运行示例

```bash
cd tutorials/07_permissions
python main.py
```

## 进一步探索

- 运行时修改 `PermissionContext.mode`，观察行为切换
- 对 MCP 工具配置权限规则，测试命名空间匹配
- 自定义 ToolBase 的 `check_permissions` 返回 PASSTHROUGH，观察引擎接管
- 给 Bash 工具配置 `"git"` 的 Allow 规则，观察命令子串匹配

## 下一期预告

**Tutorial 08: Human-in-the-Loop** — 当权限检查返回 ASK 时，如何实现用户确认和外部执行流程。
