"""ChatGPT Ads: connecting an account by its API key, its screen, and one new campaign.

Live, not mirrored. The screen reads the account from OpenAI on every
request (four calls: campaigns, figures), and a press goes to OpenAI
while the owner waits. Nothing here writes campaign rows, so the mirror,
the nightly sweeps and the agent never meet a ChatGPT account: its
``AdAccount`` row is kept ``is_active=False`` for that reason, and is the
place its name, currency and timezone are remembered.
"""
