# Skills (capability packs)

Each `*.md` file here is a capability pack: YAML frontmatter
(`id`, `name`, `segment: PARENT|ADULT|any`, `status: active|hidden`,
`priority: <int>`, `triggers: [substrings]`) + a Markdown body of guidance.
When `USE_SKILLS` is on, the agent selects the best-matching active pack(s) by
trigger-substring match and injects the body into its system prompt.
**Adding a new pack needs NO code change** — drop a `SKILL.md` here.
`README.md` is ignored by the loader.
