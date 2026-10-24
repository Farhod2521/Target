# daily_report

The daily message on the owner's phone: a finished day's figures per
campaign, and Claude's reading of them - a verdict and a line per campaign,
one or two sentences for the day, at most one thing to do today.

Answered in `core.chat.day_review.DayReview`. The rules are the whole
system prompt and carry no variables, so they are one string for every
account; the language and the business go after them, and the day's report
is the question. Every sentence passes the figure gate against the rendered
report before it reaches the phone.

## v1

First version. The day is not over when it is read, so the prompt says so
and makes "watch" the verdict for thin evidence and for a learning campaign.
Budget moves are left to the agent, which has a button for them.

## v2

The report is sent the morning after, once the night has read the day
again and the agent has had its pass. The day is finished, so "the day is
not over" became "the day is over, and one day is still little evidence",
the per-campaign no-result warning is gone from the report, and the advice
is for today rather than tomorrow.

## v3

Two changes, and both are about what the message can now say.

The report is about **one Facebook page** rather than one ad account - the
unit the subscription is sold in - so an owner with two pages gets two
reports and neither may borrow the other's figures. The page is named at the
top of the report and in the message's title.

It also carries the diagnosis of the group spending most inside each
campaign, with the figure that decided it. Until this version the message
could say a campaign did badly and never why: the cause exists in the
product but reached only the cabinet, the proposal cards and the chat. The
new section is the same rule the chat answers under - the cause is the
product's, the model explains it and never replaces it - plus the two
things the daily message adds: a cause reads several days and so does not
decide one day's verdict, and the reader already sees it under the
campaign, so it is explained rather than repeated.

## v4

The day's figures are no longer asserted to be final.

The report goes out once the night's re-read of the finished day is done -
and, where that never arrives, in the afternoon with whatever exists, so a
failed sync does not cost somebody the report entirely. Until this version
the prompt said the figures "were read again after it ended" in both cases,
so on the afternoon path the model was told something untrue and delivered
a confident verdict on a partial day. The report now carries the answer and
the prompt reads it, standing down from a **bad** verdict where the day is
not final.


`v5` adds one rule, from the first run against the real model: money is
copied as the report writes it. Three of thirteen answers spelled the
currency's code out as a word, which no check catches - the figure itself
was right - and leaves a reader holding two shapes for the same money, one
of them on the screen above and one in the sentence under it.


`v6` adds the two marks the rest of the product is written
with. A live run named a campaign three ways in three answers - in
quotation marks, lower-cased, and shortened to one word of its name -
while the lines above the sentence named it «this way», and every clause
was separated with a hyphen where the cabinet uses the long dash. Neither
is decoration: one name spelled two ways in one message reads as two
campaigns, and a hyphen between two figures reads as a subtraction.

## v7

A campaign that is paused, paused with the campaign above it or finished is
not advised about: its figures are the day's, and nothing about it is for the
owner to do. "stopped by the platform" became "the platform reported a
problem", because the state covers an advert still running with a fault.
