"""Run the one chat's live cases against the real model.

    uv run python -m tools.assistant_eval            # every case
    uv run python -m tools.assistant_eval leads      # cases whose id has "leads"

Needs ANTHROPIC_API_KEY (run it where the worker runs). Each case is asked
with the latest ``assistant`` prompt, exactly as a client's question is -
the cached base, the sections the question brings, the Context - and every
tool answers from the case's canned text. Exits 1 when a case fails, so it
can stand in a deploy script. Run it after every change to the prompt.
"""

import sys

from llmkit import ToolCall, ToolOutput, render

from app.common.llm import claude, prompts
from core.assistant.prompt import language_name, sections_for, split
from core.assistant.tools import TOOLS, with_reading
from core.chat.choices import ChoiceGate
from core.evals.assistant import AssistantCase, Run, canned, load, marks, summary


def ask(case: AssistantCase) -> Run:
    template, version = prompts().get("assistant")
    prompt = split(template)
    language = language_name(case.language)
    answer_for = canned(case, reading=with_reading)
    run = Run(answer="")

    def run_tool(call: ToolCall) -> ToolOutput:
        run.called.append(call.name)
        return ToolOutput(text=answer_for(call.name))

    gate = ChoiceGate()
    with claude(cached=True) as client:
        stream = client.converse(
            prompt=case.question,
            system=render(prompt.base, {"language": language}),
            system_tail=render(
                prompt.tail(
                    sections_for(context=case.context, question=case.question),
                    context=case.context,
                ),
                {"language": language},
            ),
            prompt_name="assistant",
            prompt_version=version,
            max_tokens=1600,
            tools=TOOLS,
            run_tool=run_tool,
        )
        words = [gate.feed(piece) for piece in stream]
    words.append(gate.flush())
    run.answer = "".join(words).strip()
    run.cost_micros = int(getattr(stream.result, "cost_micros", 0) or 0)
    return run


def main(argv: list[str]) -> int:
    wanted = argv[1] if len(argv) > 1 else ""
    cases = [case for case in load() if wanted in case.id]
    results = []
    for case in cases:
        run = ask(case)
        print(
            f"\n--- {case.id}  (tools: {', '.join(run.called) or 'none'})\n{run.answer}"
        )
        results.append((case, marks(case, run)))
    passed, total, lines = summary(results)
    print("\n" + "\n".join(lines))
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
