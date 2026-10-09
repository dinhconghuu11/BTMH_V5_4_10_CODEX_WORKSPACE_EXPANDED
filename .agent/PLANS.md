# BTMH ExecPlans

Use an ExecPlan for substantial refactors, cross-cutting performance work, database migrations, security-sensitive changes, or work touching more than three subsystems.

Each plan must contain:
- Goal and user-visible success criteria
- Current architecture and observed failure
- Files/modules expected to change
- Explicit non-goals / protected areas
- Migration or rollback strategy
- Test plan
- Security/privacy considerations
- Step-by-step implementation checkpoints
- Acceptance evidence

Keep the plan updated as implementation changes. Prefer measurable acceptance criteria such as FPS, latency, queue depth, test counts, and persistence behavior.
