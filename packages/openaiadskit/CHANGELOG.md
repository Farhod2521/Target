# openaiadskit — o'zgarishlar tarixi

Semantik versiyalash. OpenAI Ads API versiyasi (`v1`) paket versiyasidan
alohida — u `client.py` dagi `API_VERSION` konstantasida.

## 0.1.0 — 2026-11-02

Birinchi reliz: ChatGPT Ads (OpenAI Advertiser API) bilan ishlash.

### Qo'shildi
- `AdsClient(api_key=)` — REST + httpx, `https://api.ads.openai.com/v1`.
  `get`, `post` (`Idempotency-Key` bilan), `upload` (multipart rasm) va
  `pages` (cursor: `after` / `has_more` / `last_id`).
- Xatolar: `OpenAIAdsUnreachable` (yetib bormadi, qayta yuborish xavfsiz),
  `OpenAIAdsOutcomeUnknown` (ketdi, javob kelmadi), `OpenAIAdsAPIError`
  (OpenAI rad etdi: HTTP holati, `type`, `code`, `param`, `x-request-id`,
  `Retry-After`). `translate_error` — HTTP holati bo'yicha `adskit` xatosiga.
- `read_ad_account` (kalit qaysi akkauntniki: nomi, valyutasi, vaqt zonasi,
  brend tekshiruvi holati) va `search_places` (`geo_lookup/search`).
- `OpenAICampaigns` (`CampaignControlPort`): kampaniya → ad group → reklama
  ro'yxatlari (arxivlanganlar kirmaydi), `get_status`, `count_adsets`,
  `set_status` (`activate` / `pause`), `set_budget` (kunlik, micros),
  `set_spend_cap` (umrbod limit), `set_end_time`, `delete` (`archive`).
  Yetkazish holati `serving_issues` dan o'qiladi. `read_objects`,
  `read_account`, `get_preview` — `PortNotAvailable`.
- `OpenAIMetrics` (`MetricsPort`): `/ad_account/insights` dan kunlik qatorlar
  va davr bo'yicha yig'indi (`fetch_totals`). Breakdown va reach — bo'sh.
- `KeyConnect` (`ConnectPort`): ulanish API kalit bilan; OAuth redirect yo'q.
- `launch.create_chat_campaign` — kampaniya (pauzada) → ad group → chat card
  → yoqish. Biror qadam yiqilsa kampaniya arxivlanadi. Har yaratishda
  `{key}:{qadam}` idempotency kaliti.
- `adapter.bundle(rehearse_writes=)` — registry uchun.
