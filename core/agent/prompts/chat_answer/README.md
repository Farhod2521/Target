`chat_answer` is the only prompt in this library that asks for free text
rather than a schema. The answer is a sentence somebody reads, not data
the product acts on - and what makes it trustworthy is not the prompt but
`core/chat/verify.py`, which will not carry a figure the context did not
supply.

`v2` adds two sections and changes nothing else. One says what to do when
the context ends with a single suggestion the reader clicked through from
(B5.2's link from the agent card). The other says that agreeing in the
conversation is not a decision: chat writes nothing, so "ha, qil" has to be
answered with where the button is rather than with a confirmation.

`v3` adds two more and changes nothing else. One says that the context is
now chosen for the question - `core/chat/route.py` decides which sections
of the account travel with it - and that a section named under "Not
included" exists and was left out, so an answer must name the screen rather
than conclude the account is empty. The other is the counterpart of v2's
suggestion section, for a question that arrived from a line of the
cabinet's waiting list instead of from a proposal's card.

`v4` adds one section and changes nothing else. The context can now carry
the rung below the campaigns - one line per ad group, with its audience,
its cost per enquiry and the provider's verdict on it - because a fault
lives on a group and the campaign above it goes on reporting itself as
active. The section says to prefer those lines for a question about a
group or about something being broken, and to say what the provider's
verdict *means* rather than quoting it.

`v5` opens the one door that was deliberately shut. An answer may now end
with a line naming an action, and the reader is shown a button for it -
which is what turns "bajarildi, lekin natija bo'lmadi" from a dead end into
a conversation with a next step.

What makes that safe is not the prompt. The context carries a closed list of
short keys built from proposals the agent has already made, the line is
split off the answer before anybody reads it (`core/chat/choices.py`), and
the verb on the button, the advert it acts on and the service behind it are
all read back out of the card the actions screen draws. A key that was never
offered resolves to no button. The prompt's job is only to say when to write
one and, more importantly, when not to: at most two, never invented, never
mentioned in the prose, and never argued for.

The section that said "you cannot do anything" was rewritten rather than
deleted. The promise it protected - the model does not decide what happens
to somebody's money - is unchanged; what moved is that refusing to offer a
button was never the thing that kept it.

`v6` lets the assistant see what the nightly diagnosis sees. A group line
can now carry its cause - found by `core/agent/diagnosis.py`, in the card's
own sentence - with the rates the cause was decided on beside the
account's. Two new sections can travel: "Adverts", each with its own words
and the provider's rating, and "Lead forms" with "Website pages", which is
what a click lands on. The proposal list carries each proposal's cause and
the before-and-after figure its verdict was read from. The qualified-lead
figures are gone from the totals and the campaigns: the mark they rest on
is switched off, so they read as nought.

The rule the new sections are written around is the product's: the code
finds the cause and the model explains it. So the prompt says never to
replace a cause, never to add one, and to say "no single cause" when that
is what the line says. The advert's words arrive with a second rule - talk
about them, but do not write a finished replacement, because new words are
checked against the offer before anybody sees them and a conversation is
not.

`v7` gives the assistant look-ups - the tools declared in
`core/chat/lookups.py` and read in `apps/chat/selectors/lookups/`. The
context still travels chosen for the question and bounded to the current ad
account; what changed is what an answer does when that is not enough. The
section that said "name the screen" for anything under "Not included" is
replaced by one that says to look it up, across every ad account and page in
the subscription, and to name a screen only for what no look-up returns.
The figures rule now allows a figure a look-up returned - the gate adds each
result's figures as it arrives - and the section keeps the promise the
product makes about leads: counts, never a person. A section on reading an audience
goes with `audience_details`: the settings by name, and the money split by
age and gender, region and placement with the verdict `compare_segments`
gives each slice - which the model explains and never replaces.

`v8` changes the unit the assistant thinks in. The context is no longer one
ad account's dashboard: it is the subscription cut by Facebook page - what
each page spent, brought in and ran - because that is what this product is
sold in, and one page's advertising can be paid for out of any number of ad
accounts. A new section says so, and says the other half of it: a page the
subscription does not cover is not describable at all, so a question about
one gets "it is not in your subscription" and nothing else. The look-ups
enforce the same edge and answer "not in this subscription" when asked past
it; the prompt says that is an answer rather than an error to retry.

The waiting-list section is rewritten for the reply: the line is quoted
above the box now, so the reader may send it with nothing typed, and the
prompt says to answer about the quoted line without asking which one is
meant and without reading its own sentence back to them.

One fix with no new behaviour behind it: the off-topic sentence had begun
turning up as a preamble to real answers ("your other questions are not
about advertising"). It now says explicitly that it is the whole answer or
it does not appear.

`v9` adds one section and changes nothing else. The context now counts each
campaign's result in the kind it was bought for - leads, conversations,
calls, visits, showings - where it used to count only forms, so a chat
campaign's forty conversations read as "leads 0". The section says to name
each kind by its own word, never to add two kinds together, and never to
call an account empty because one kind is nought.

`v10` rewrites one section and one sentence and changes nothing else. The
conversation is now about the page the owner is on: the context and the
look-ups carry that page alone, whichever ad accounts pay for it. The
section says so, and says that a look-up naming something "on another page
of this subscription" is answered by pointing to that page rather than
guessed at. The look-up sentence now reads "this page" instead of "every
page in the subscription".

`v11` adds one section and two sentences. The conversation now reads only
the advertising this product made: the campaigns somebody built in Ads
Manager are left out of the context and of every look-up, the way the
cabinet and both messages already leave them out of their figures - so the
assistant stopped being the one surface reporting a larger total than every
screen. The new section says what to do when a look-up answers "Built in
Ads Manager": the campaign is real and on their own screen, so it is named
and pointed at rather than called missing. The look-up list gains
`preparations`, which reads the campaigns this product was building - the
one part of the product that exists in no mirror, and so the one question
("why was my campaign not created") that used to be answered with "open the
screen".


`v12` rewrites "The adverts themselves". The section was written when the
night agent still wrote replacement copy; it stopped doing that, so the
assistant was pointing at a proposal that no longer arrives and offering
its own lines instead - which nothing can apply once a campaign is running.
The owner's rule is that the picture is what stops somebody scrolling, so
the answer to an ignored advert now goes in one order: what the provider
says about it, how many of the people shown it clicked against this
advertiser's own adverts, then "put a new picture or video in the library".
Writing or suggesting a line is refused outright, with one exception - an
advert the provider *refused*, where the words are the fault it named and
saying what must come out of them is a repair rather than a rewrite.


`v13` came from the first run against the real model. Two things showed up
that no test catches: money written back as a word ("45 dollar") where
every screen in the product writes the currency's code, and the provider's
own English label quoted in brackets beside the plain-Uzbek explanation of
it. The first is now a rule in "Figures" - money is copied, not retyped -
and the second tightens the rule that was already there: not in quotation
marks, not in brackets, not translated.


`v14` is the second finding from the same live run. The context labels the
platform "provider" - deliberately, because the domain code never names one
- and the model read the label as a name and put it in an Uzbek sentence,
where it reads as an internet provider. The screens say "Meta", so the
answer says "Meta"; the context keeps its neutral word, which is what makes
a second platform a matter of adding an adapter rather than rewriting the
assistant.


`v15` gives the answer the same marks as the rest of the product. The
"How to write" section said what not to say and almost nothing about how
what is said should look, so one run wrote a campaign's name in `"these"`,
the next in bold, and every sentence separated its clauses with a hyphen -
beside a cabinet and a morning message that write «this» and a long dash.
The section now names five marks and one shape, and the shape is the part
that is not typography: two things compared go one to a line, `«nom» —
45 USD · natija yo'q`, and the renderers draw a line of that shape as a
row with the name in one column and its figures in the other. A sentence
comparing the same two campaigns is still drawn as a sentence, which is
the point - the model chooses between a paragraph and a row by writing
one or the other, and cannot ask for anything the product has not built.

Tables go with it. They were allowed for exactly this comparison and are
unreadable at a phone's width on both surfaces: the browser scrolls one
sideways and Telegram, which has no table at all, joins the cells with a
separator. Both renderers still understand one, because a model that
writes a table anyway should not have its answer rendered as pipes.


`v16` is the live run of v15, which held the shape and let two things
through. A campaign was named «this way» in five answers out of six and in
"these" in the sixth, where the name was an advert's rather than a
campaign's - so the rule now covers everything the answer quotes, not only
the things that were listed. And one sentence read "hozircha faol reklama
campaign ishlamayapti": the jargon list names the words a media buyer uses
and had nothing to say about the ordinary English word for a thing this
product calls "kampaniya". Both are checked by the graders now, which is
what makes the next run able to answer whether this version held.


`v17` says the same two rules as characters rather than as categories,
because that is how the run before it missed them. Told that names go in
«these» and screens go bare, one answer put the screen in «these» and the
advert's own headline in "these" - the rule was read as being about names,
and everything the model did not file as a name went somewhere else. So
the mark itself is the rule now: the `"` character does not appear in an
answer, and a screen carries no brackets of any kind. The grader checks
both, outside «the brackets», where what is written is the account's
spelling rather than the model's.


`v18` closes the way the platform's neutral label keeps arriving: spelled
into the reader's own alphabet. Told never to write "provider", a run
wrote "provayder bahosi" - the rule kept as an English word and broken as
an Uzbek one, in a sentence to somebody who has only ever seen "Meta" on
their screens. The graders carry the spellings now, so this is a thing a
run can fail on rather than a thing somebody has to notice.


`v19` adds two things the assistant may do and changes nothing else. An
answer that asks the owner a question may end with a `%%REPLY%%` line of
two to five short answers, which become buttons that send their words as
the owner's next message (`core/chat/choices.py` splits the line off and
checks its figures). And the owner may ask for a plan for a new video:
the assistant asks what it is missing one question at a time, offers two
or three ideas as replies, and writes the chosen one as numbered scenes.
That is not the rewrite of a running advert the prompt still forbids - a
new video goes into the library, which is where that section already
sends them.

`v24` adds one paragraph to "Figures" and changes nothing else. A visitor
has no account, so the gate has nothing to let a money figure through
against and every price the model wrote as general advice reached the
landing page as a gap. The paragraph asks for words instead of money,
per-cents and result costs when the context is empty; head counts stay,
and the gate now passes them for a visitor.

`v25` adds "Switched off is not a problem to fix" before "Why a group is not
working". The state label reaches the model in the reader's language, so the
group and advert lines now carry ", switched off" in English for anything
paused, paused above or finished, and the section says to propose no fix for
those and to answer about the running ones first. A refused advert is not
switched off and keeps its repair.

`v26` lets the assistant prepare a change the owner asked for - a daily
budget, a pause, switching something back on - through the `propose_change`
look-up. Nothing is carried out by the model: the look-up runs the campaigns
screen's own checks without opening a change, the prepared change is kept on
the answer as a confirm button, and pressing it calls the campaigns screen's
service, which checks everything again (`app/modules/chat/services/changes.py`).
