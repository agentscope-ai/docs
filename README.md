# AgentScope Documentation

This repository is the source for the unified
[AgentScope documentation site](https://docs.agentscope.io). It publishes English and
Chinese documentation for [AgentScope](https://github.com/agentscope-ai/agentscope) and
[ReMe](https://github.com/agentscope-ai/ReMe) with
[Mintlify](https://mintlify.com).

## Documentation Sets

The two projects share one site but keep separate content and release models:

| Project | Documentation scope | Live documentation | Update model |
|---|---|---|---|
| AgentScope | Building, operating, and deploying agent applications | [AgentScope docs](https://docs.agentscope.io/stable/en/index) | Immutable version directories |
| ReMe | File-native agent memory, workflows, integrations, and stable contracts | [ReMe docs](https://docs.agentscope.io/reme/latest/en/overview) | One continuously updated `latest` version |

## ReMe Documentation

The ReMe repository [README](https://github.com/agentscope-ai/ReMe#readme) is the concise
project entry point. This repository owns the complete public documentation: concepts,
verified workflows, integrations, reference material, troubleshooting, and contribution
guidance.

ReMe documentation should preserve the product principles expressed by its README:

- memory files are user-owned source data;
- indexes, graphs, and caches are rebuildable derived state;
- conversations and resources become correctable, traceable Markdown memory;
- Python, AgentScope, MCP, CLI, HTTP, plugins, and Skills are integration boundaries over
  the same file-native memory model.

The current ReMe content is organized by user goal:

| Area | Pages | Purpose |
|---|---|---|
| Get Started | [Overview](reme/latest/en/overview.mdx), [Quick Start](reme/latest/en/quickstart.mdx), [Concepts](reme/latest/en/concepts.mdx) | Explain the product, complete the first memory loop, and establish its principles |
| Integration | [Integration overview](reme/latest/en/integration/overview.mdx), [Deployment](reme/latest/en/integration/deployment.mdx), [Python SDK](reme/latest/en/integration/python-sdk.mdx), [Plugins](reme/latest/en/integration/plugins.mdx) | Choose and implement the correct runtime boundary |
| Resources | [Reference](reme/latest/en/reference.mdx), [FAQ](reme/latest/en/faq.mdx), [Contribution](reme/latest/en/contribution.mdx) | Find stable contracts, solve common problems, and contribute changes |

Chinese pages mirror the same structure under `reme/latest/zh/`. Update both languages
together and keep their intent, headings, examples, and links aligned.

## Local Development

Use an active Node.js LTS release (Node 20 or 22).

Install the [Mintlify CLI](https://www.npmjs.com/package/mint):

```bash
npm i -g mint
```

From the repository root, validate the site or start a preview:

```bash
mint validate
mint dev
```

The preview is available at `http://localhost:3000` by default.

## Repository Structure

```text
.
├── versions/
│   └── <version>/{en,zh}/   # Versioned AgentScope documentation
├── reme/
│   └── latest/{en,zh}/      # Current ReMe documentation
├── images/                  # Shared static assets
├── scripts/                 # Documentation maintenance scripts
├── docs.json                # Mintlify navigation and redirects
└── CLAUDE.md                # Writing and review guidelines
```

## Content Boundaries

Keep public documentation focused on user goals and stable behavior:

- Verify ReMe behavior against current code, public schemas, tests, CLI help, and
  `reme/config/default.yaml`.
- Explain the stable contract and link to authoritative source instead of duplicating
  implementation details.
- Keep concepts focused on product intent; place detailed development mechanics in source
  code, tests, and repository-local guidance.
- Lead with the outcome, use direct language, and introduce every table, image, diagram,
  and code block.
- Start each MDX page with `title` and `description` frontmatter.

See [CLAUDE.md](CLAUDE.md) for the complete writing and component guidelines.

## Version Management

AgentScope documentation is immutable within each published version directory. For a new
AgentScope release:

1. Copy the latest relevant version into a new project version directory.
2. Update every version-specific internal link in the copied pages.
3. Add the version under the matching project tab for both languages in `docs.json`.
4. Point the relevant `latest` or `stable` redirect at the new version. Make a new
   stable release the default in both languages; development versions keep the
   existing stable default.
5. Run `mint validate` before submitting the change.

AgentScope versions can be created with `scripts/create-version.sh`.

ReMe does not keep historical release directories. Update `reme/latest/{en,zh}/`
directly, keep canonical internal links under `/reme/latest/...`, and leave its
`docs.json` version label as `latest`. The `/reme/stable/...` alias and obsolete
numeric-version URLs redirect to the current pages for compatibility.

## Contribution Workflow

When adding or updating documentation:

1. Verify the behavior in the corresponding project source.
2. Update the correct project, version, and language pages.
3. For ReMe, make the equivalent English and Chinese changes in `reme/latest/`.
4. Update `docs.json` when navigation, versions, or compatibility redirects change.
5. Check page links and run `mint validate` before submitting a pull request.

Run these checks from the repository root before submitting:

```bash
git diff --check
mint validate
```

## Resources

- [AgentScope GitHub](https://github.com/agentscope-ai/agentscope)
- [ReMe GitHub](https://github.com/agentscope-ai/ReMe)
- [ReMe English documentation](https://docs.agentscope.io/reme/latest/en/overview)
- [ReMe 中文文档](https://docs.agentscope.io/reme/latest/zh/overview)
- [Mintlify Documentation](https://mintlify.com/docs)

## AI Documentation Index

Mintlify generates `llms.txt` and Markdown exports automatically. Maintain version
selection guidance in `docs.json` under `markdown.instructions`; do not duplicate
the generated index in a manually maintained file.
