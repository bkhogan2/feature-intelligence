// Illustrative formatting fixture, not customer evidence or generated analysis.
export const analysisExample = `## Illustrative analysis

**Formatting demo only.** This is not AI output or a finding about any request.

### Problem statement
A fictional team wants a clearer handoff between review stages. The cause is **unverified**; more context is needed.[^source]

> Preserve the original feedback before making an interpretation.

### Evidence and gaps
- A hypothetical observation, not validated demand.
- ~~An unsupported conclusion~~ replaced by a question.
  - What would establish whether the problem is recurring?

1. Read the original submission.
2. Record the remaining questions.

### Review checklist
- [x] Distinguish examples from evidence
- [ ] Validate the fictional problem

| Claim | Evidence | Confidence |
| :--- | :--- | :--- |
| Handoffs need attention | Illustrative example only | Unknown |
| A workflow change would help | No supporting evidence | Unknown |

### Implementation note
Use an explicit \`pending\` value rather than inferring a decision.

\`\`\`json
{ "exampleOnly": true, "decision": "pending" }
\`\`\`

Read the [Markdown reference](https://commonmark.org/help/) or return to the [inbox](/#inbox).

![Illustrative diagram](https://example.invalid/diagram.png)

[^source]: Fictional source included solely to demonstrate footnotes.
`;
