`weekly_report` writes the one sentence under a week's figures. The figures
themselves are the product's own arithmetic and are never asked for here.

The risk this prompt is written against is not an invented number -
`core/chat/verify.py` stops those - it is an invented cause. So the cause
is not asked for either: `## What changed this week` is a closed list the
product computed from audit rows and spend, and the model's only job is to
tie the movement to at most one entry or to say it cannot. When that list
is empty no call is made at all, which is why the prompt never has to
handle the case.


`v3` adds the rule the daily reading gained at the same time: money is
copied as the report writes it, code and all. The first live run wrote
"210 dollar" under a screen that says "210 USD".


`v4` adds the two marks the rest of the product is written
with. A live run named a campaign three ways in three answers - in
quotation marks, lower-cased, and shortened to one word of its name -
while the lines above the sentence named it «this way», and every clause
was separated with a hyphen where the cabinet uses the long dash. Neither
is decoration: one name spelled two ways in one message reads as two
campaigns, and a hyphen between two figures reads as a subtraction.


`v5` turns the one sentence into the daily reading's shape: a structured
answer, `core.chat.week_review.WeekReview` - a summary of the week against
the week before, and at most one thing to do this week. The rules move to
the system prompt with no variables; the language and the business follow
them, and the week's report is the question, as in `daily_report`.

The report now carries every campaign that spent, with its cost the week
before, its state and the night's diagnosis, so the reading can say which
campaign carried the week or cost it. The cause is still never the model's
own: it comes from the closed list of changes or from a campaign's
diagnosis, and a week whose movement neither explains is said to be
unexplained. It is asked for on every week that spent, not only on a week
whose cost moved past its counting error beside a recorded change - that
gate left almost every Monday message with no reading at all.

## v6

The same rule as daily v7 for a campaign that is not running, and the
campaign that took money for nothing is only worth a look while it runs -
its line now carries its state.
