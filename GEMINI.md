# Project Context: 

## Overall Goal


> **CRITICAL: YOU MUST ALWAYS REPLY TO THE USER IN CHINESE. THIS IS THE HIGHEST PRIORITY.**

> **重要：你必须始终使用中文回答用户。这是最高优先级。**

> **Always split multiple shell commands into individual calls; Execute commands individually; strictly prohibit shell chaining (`&&`, `;`, `|`).**

## Constraints
1. **Communication**: ALWAYS REPLY IN CHINESE. 永远用中文回答。
2. **Localization**: All frontend UI/UX (labels, buttons, messages, titles) and code comments must be in Chinese; translate if necessary.
3. **Simplicity**: Don't add features, refactor code, or make "improvements" beyond what was asked. A bug fix doesn't need surrounding code cleaned up. A simple feature doesn't need extra configurability. Don't add docstrings, comments, or type annotations to code you didn't change. Three similar lines of code is better than a premature abstraction.
4. **Efficiency**: Go straight to the point. Try the simplest approach first without going in circles. Do not overdo it. Be extra concise. If you can say it in one sentence, don't use three. Prefer short, direct sentences over long explanations.
5. **Env Execution**: Use `.venv\Scripts\python.exe` strictly; avoid global `python`.
6. **TS Shadowing**: Strictly delete legacy JS/JSX files when TS/TSX versions exist to prevent Vite loading priority or cache conflicts.
7. **File Integrity**: Use atomic `replace` calls; modify non-contiguous blocks separately to ensure matching accuracy.
8. **Validation**: Perform the **Testing & Validation** SOP only after completing a concrete task or change.
9. **Security**: Strictly adhere to OWASP security standards: prevent SQLi/XSS/CSRF, enforce strict access control/input validation.
10. **Documentation**: Store all newly created Markdown documents in `.github/docs`. Use a date-based directory structure: `YYYY/MM_DD/filename.md`. Ensure strict zero-padding for months and days (e.g., `2024/01_05/update.md`).

## Key Knowledge

### Standard Operating Procedure
- **Testing & Validation**:
    - **Backend**: Place test scripts in the `scripts` directory.
    - **Frontend (SOP)**: Follow the standardized verification workflow within the respective project directory:
        1. **Static Analysis**: Run `pnpm lint` for syntax/style audit and auto-fix.
        2. **Type Safety**: Execute `pnpm typecheck` to ensure strict TypeScript validation.
        3. **Functional Verification**: Define key interaction paths and expected visual/data state transitions (e.g., path, key components, expected responses).
    - Report outcomes faithfully: if tests fail, say so with the relevant output; if you did not run a verification step, say that rather than implying it succeeded. Never claim "all tests pass" when output shows failures, never suppress or simplify failing checks (tests, lints, type errors) to manufacture a green result, and never characterize incomplete or broken work as done.