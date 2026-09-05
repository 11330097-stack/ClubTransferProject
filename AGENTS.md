# ClubTransferProject Agent Rules

## General
- Read before modifying.
- Prefer the smallest valid change.
- Avoid unrelated refactoring.
- Preserve existing behavior unless explicitly changed.
- Match existing project structure.

## Database Safety
- Do not perform destructive database operations without authorization.
- Do not delete migration history.
- Only change schema when the task genuinely requires it.

## Business Invariants
1. A student belongs to at most one active club.
2. Every active club has exactly one valid president.
3. The president belongs to that club.
4. Member count never exceeds max_members.
5. Disabled clubs cannot accept members.
6. Club deactivation must leave data consistent.
7. Role permissions must not cross boundaries.
8. Backend authorization is mandatory.
9. Displayed statistics must match actual data.
10. Deletes and role changes must not create invalid references.

## Security
- Never rely only on frontend validation.
- Verify privileged actions on the backend.
- Do not expose secrets.
- Do not deploy automatically.

## Verification
- Reproduce issues when possible.
- Fix the root cause.
- Add regression tests where appropriate.
- Run relevant tests.
- Run python manage.py check.

## Completion
- All stated requirements are satisfied.
- Relevant tests pass.
- Core business invariants still hold.
- Report changed files, tests performed, and remaining risks.