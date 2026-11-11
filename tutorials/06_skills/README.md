# Tutorial 06: Skill — 用 Markdown 扩展 Agent 能力

> **什么时候需要这个？** 某个任务需要"按一套套路组合多个工具"（比如：先采样数据 → 决定图表类型 → matplotlib 画图 → 保存）。你想把这套套路用 Markdown 沉淀下来，让 Agent 按需加载，而不是把它塞进 system prompt 让模型每次重新摸索。

## 本章基于前序章节

- **T03 — `Toolkit` / 内置工具**：Skill 不替代工具，它指导 Agent 如何**组合**已有工具（Bash / Read / Write 等）完成复杂任务。
- **T04 — `ToolGroup`**：Skill 可以挂进任一 ToolGroup，跟随该组激活/停用。

## 你将学到

- Skill 是什么、不是什么
- 如何编写 `SKILL.md`
- 如何把 Skill 注册到 Toolkit
- Agent 运行时如何发现和使用 Skill

## 前置要求

- 完成 Tutorial 05
- 理解 Toolkit 和 ToolGroup 的基本概念

## 核心概念

### Skill — 是什么

**一组 Markdown 格式的操作指南**，告诉 Agent 如何组合现有工具完成特定任务。

Skill **不是**工具——工具有 Schema、可以被 LLM 直接调用；Skill 是写给 Agent 看的"操作手册"，Agent 读完后用已有的工具（Bash、Read、Write 等）去执行。

```
工具 = 原子操作（读文件、执行命令、查询数据）
Skill = 操作指南（如何组合工具来生成图表、写报告）
```

**什么时候用：** 你发现某类任务需要固定的多步骤套路（采样 → 选图表类型 → matplotlib 画图 → 保存），想把这套流程沉淀下来复用，而不是每次都靠模型自己摸索。

### SKILL.md — 怎么写

这一设计参考了 [Claude Code 的 Skill 规范](https://docs.anthropic.com/en/docs/claude-code/skills)。每个 Skill 是一个**目录**，包含必需的 `SKILL.md` 和可选的资源文件（脚本、参考文档、模板等）：

```
skills/
├── chart_generator/
│   ├── SKILL.md              # 必需：frontmatter 元数据 + Markdown 指令
│   └── scripts/              # 可选：可复用脚本
│       └── plot.py
└── report_writer/
    ├── SKILL.md
    └── assets/                # 可选：模板、参考文档等资源
        └── report_template.md
```

`SKILL.md` = YAML frontmatter（元数据） + Markdown 正文（操作指令）：

```markdown
---
name: chart_generator
description: Generate charts using matplotlib. Supports bar, line, pie.
---

# Chart Generator

## 使用流程

1. 读取用户提供的数据文件
2. 根据数据特征选择图表类型
3. 使用 `scripts/plot.py` 生成图表
4. 保存到用户指定的输出路径
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | 技能名称，Agent 通过此名称引用 |
| `description` | 是 | 技能描述，帮助 Agent 判断何时使用该技能 |

### 注册与使用

写好 SKILL.md 后，通过 Toolkit 的 `skills_or_loaders` 参数注册（Toolkit 的基本用法见 T03）。

`skills_or_loaders` 接受三种类型的值，适用于不同场景：

```python
import time

from agentscope.skill import LocalSkillLoader, Skill

toolkit = Toolkit(
    tools=[Read(), Bash()],
    skills_or_loaders=[
        # 方式 1：字符串路径 — 直接指向某个 Skill 目录
        # 适用于：加载单个已知的 Skill
        "skills/chart_generator",

        # 方式 2：LocalSkillLoader — 扫描目录下的所有子目录
        # 适用于：批量加载一个目录下的多个 Skill
        LocalSkillLoader("skills", scan_subdir=True),

        # 方式 3：Skill 对象 — 直接传入已构造的 Skill 实例
        # 适用于：程序化构建 Skill（如从数据库或远程加载）
        Skill(
            name="...",
            description="...",
            dir="...",
            markdown="...",
            updated_at=time.time(),
        ),
    ],
)
```

当当前可用工具组中存在 Skill 时，系统会暴露名为 `Skill` 的只读工具（Python 实现类叫 `SkillViewer`）。Agent 运行时的流程：

```
系统提示中列出所有技能的 name + description（占用极少上下文）
  ↓
Agent 根据用户请求，判断需要使用某个技能
  ↓
调用 Skill(skill="chart_generator") 读取完整的 Markdown 指令
  ↓
按照指令使用 Bash/Read/Write 等工具执行
```

这就是**渐进式加载**——20 个 Skill 的元数据只占很少的上下文空间，完整指令只在需要时才加载。

> Skill 也可以放进 ToolGroup 随组激活/停用，详见 T04。

## 示例：给 DataMuse 添加技能

本期创建两个 Skill：

1. **chart_generator** — 指导 Agent 用 matplotlib 生成图表
2. **report_writer** — 指导 Agent 生成结构化的 Markdown 分析报告

Agent 在收到相关任务时，先通过 `Skill` 工具读取技能指令，再用 Bash、Read 等工具执行。

## 运行示例

```bash
cd tutorials/06_skills
python main.py
```

## 进一步探索

- 创建自己的 Skill（如 `data_cleaner`），处理数据清洗任务
- 将 Skill 放入不同的 ToolGroup，测试激活/停用行为
- 在 Skill 中引用资源文件（模板、配置），观察 `dir` 字段的作用
- 尝试实时修改 SKILL.md 内容，观察 LocalSkillLoader 的缓存刷新

## 下一期预告

**Tutorial 07: Permission 系统** — 控制 Agent 的行为边界，配置五种权限模式和精细的规则。
