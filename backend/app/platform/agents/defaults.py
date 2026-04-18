from __future__ import annotations

from app.platform.agent_tasks.schemas import TaskClass
from app.platform.agents.schemas import (
    AgentCatalogDefinition,
    AgentDefinition,
    AgentWorkflowActionDefinition,
    AgentWorkflowDefinition,
    AgentWorkflowStepDefinition,
    RuntimeDefinition,
)

DEFAULT_AGENT_CATALOG = AgentCatalogDefinition(
    agents=[
        AgentDefinition(
            id="planner",
            display_name="Planner",
            description="Breaks work into clear steps, tradeoffs, and execution plans.",
            supports_streaming=True,
            system_prompt="Act like a pragmatic planning partner. Clarify sequencing, assumptions, decision points, and the next executable steps.",
            runtime="planner_runtime",
        ),
        AgentDefinition(
            id="rag-analyst",
            display_name="RAG Analyst",
            description="Analyzes requests with retrieval-oriented runtime hints.",
            supports_streaming=True,
            system_prompt="Act like a retrieval-aware analyst. Call out uncertainty, identify where external context would help, and separate evidence from inference.",
            runtime="rag_analysis_runtime",
        ),
        AgentDefinition(
            id="coder",
            display_name="Coder",
            description="Implements repository changes through the internal task runtime.",
            supports_streaming=True,
            system_prompt="Act like a careful implementation engineer. Prefer direct repository changes, preserve local patterns, and verify the result before wrapping up.",
            workflow=AgentWorkflowDefinition(
                goal="Implement the requested fixes, validate the changes, and send the result back for review when the implementation succeeds.",
                max_iterations=3,
                entry_step="implement-fixes",
                steps=[
                    AgentWorkflowStepDefinition(
                        id="implement-fixes",
                        title="Implement Fixes",
                        instructions="Apply the requested remediation changes and run the most relevant validation before reporting completion.",
                        output="Summarize the implementation details, validation performed, and any remaining caveats.",
                        on_success=AgentWorkflowActionDefinition(
                            action="handoff",
                            to="reviewer",
                            prompt="Re-review the implementation, confirm the fixes, and run validation again before closing the loop.",
                        ),
                        on_failure=AgentWorkflowActionDefinition(action="finish"),
                    )
                ],
            ),
            runtime="coding_runtime",
        ),
        AgentDefinition(
            id="reviewer",
            display_name="Reviewer",
            description="Reviews changes with approval gating before execution continues.",
            supports_streaming=True,
            system_prompt="Act like a rigorous reviewer. Prioritize correctness risks, failing tests, regressions, and specific remediation guidance over general summaries.",
            workflow=AgentWorkflowDefinition(
                goal="Review changes, validate them with tests when possible, and hand a concrete fix report back to the coder persona.",
                max_iterations=3,
                entry_step="review",
                handoff_to="coder",
                handoff_summary_prompt="Summarize the root cause, failing evidence, and recommended fixes in a form the coder agent can implement directly.",
                steps=[
                    AgentWorkflowStepDefinition(
                        id="review",
                        title="Review And Validate",
                        instructions="Run validation, inspect repository context when needed, and produce a fix-oriented report if issues remain.",
                        run="pytest",
                        output="Capture validation evidence, likely root causes, and the final review decision.",
                        on_success=AgentWorkflowActionDefinition(action="finish"),
                        on_needs_changes=AgentWorkflowActionDefinition(
                            action="handoff",
                            to="coder",
                            prompt="Summarize the root cause, failing evidence, and recommended fixes in a form the coder agent can implement directly.",
                        ),
                        on_failure=AgentWorkflowActionDefinition(action="finish"),
                    ),
                ],
            ),
            runtime="review_runtime",
        ),
    ],
    runtimes=[
        RuntimeDefinition(
            key="planner_runtime",
            task_class=TaskClass.PLAN_ONLY,
            route_profile="cheap",
            approval_mode="none",
            prompt_preamble="Focus on sequencing, assumptions, and clear next steps.",
        ),
        RuntimeDefinition(
            key="rag_analysis_runtime",
            task_class=TaskClass.ANALYZE,
            route_profile="cheap",
            approval_mode="none",
            prompt_preamble="Add retrieval-aware analysis and note where external knowledge would improve confidence.",
        ),
        RuntimeDefinition(
            key="coding_runtime",
            task_class=TaskClass.IMPLEMENT,
            route_profile="implementation",
            approval_mode="none",
            prompt_preamble="Prefer direct repository changes, preserving existing patterns and testing the result.",
        ),
        RuntimeDefinition(
            key="review_runtime",
            task_class=TaskClass.REVIEW,
            route_profile="implementation",
            approval_mode="required",
            prompt_preamble="Prioritize correctness risks, regressions, and missing tests before summaries.",
        ),
    ],
)
