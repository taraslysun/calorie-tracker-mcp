# Tablycja API Map

Source: `recon/captures/web-20260504-105333.jsonl` (logged in as taraslysun2@gmail.com).

## Base
- Host: `https://www.tablycjakalorijnosti.com.ua`
- All endpoints accept `?format=json` and return JSON envelope:
  `{"requestId":null,"code":0,"message":<str|null>,"data":<obj|null>}`
- Date format in URL paths and POST bodies: **`DD.MM.YYYY`** (e.g. `04.05.2026`).
  Diary "filled-out" endpoint uses ISO `YYYY-MM-DD`.
- Locale: `lang=ua` set on user profile, response strings localized in Ukrainian.

## Auth

| Step | Method | Path | Body | Notes |
|------|--------|------|------|-------|
| Google one-tap login | POST | `/login/one-tap?format=json` | `{"token": "<Google ID JWT>"}` | Sets session cookie. No Authorization header anywhere; cookie is the credential. |
| Active user | GET | `/user/active-user?format=json` | — | Returns full user record incl. `id`, `googleId`, `lang`, plan flags. Use as auth probe. |

**Auth strategy for our MCP server**: user obtains a Google ID token (via our AS that runs Google OAuth client) → POST it to `/login/one-tap` → store returned `Set-Cookie` jar per user (Fernet-encrypted in SQLite). Refresh by re-running login when 401 observed.

No CSRF token observed; CORS-style `origin`/`referer` checked (must match `https://www.tablycjakalorijnosti.com.ua`).

## Profile

| Method | Path | Body | Description |
|--------|------|------|-------------|
| GET | `/user/active-user?format=json` | — | Compact user record (`id`, `email`, `sex`, `birthYear`, `lang`, `googleId`, plan flags, `countDiet`, `countWeight`). |
| GET | `/user/settings/profile/form?format=json` | — | Full profile incl. `height`, `weight`, `year`, `targetWeight`, `drinkRegime` (L), `amr` (activity multiplier), `energyUnit`, `ownDiaryTimeRatios`, `ownNutrients` goals (protein/carb/fat/fiber...). |
| POST | `/user/settings/profile/form?format=json` (suspected; not yet captured) | profile object | Save edits. **TODO**: capture during a real edit+save. |

## Food diary

| Method | Path | Body | Description |
|--------|------|------|-------------|
| GET | `/user/diary/{DD.MM.YYYY}/get?format=json` | — | Day diary. `data.times[]`: 6 meals (Сніданок, Перший перекус, Обід, Другий перекус, Вечеря, Третій перекус) each with `id` 1–6, `foodstuff[]`, `notes[]`, `energyTotal`, `dailyTimeUserRatio`. |
| GET | `/user/diary/summary/{DD.MM.YYYY}/get?format=json` | — | Daily totals: energy goal/actual, water (`Питний режим`), target weight, plus `itemsDynamic` macro breakdown (protein/carb/fat). |
| GET | `/user/diary/filled-out/{YYYY-MM-DD}/` | — | Calendar markers (which days have entries). |
| GET | `/user/foodstuff/add/form/{foodstuffGuid}/{DD.MM.YYYY}/get?format=json` | — | Pre-fill form for adding food. Returns full add payload skeleton incl. `unitOptions[]` (e.g. `100 г`, `порція (150 г)`, `1 г`), `diaryTimeOptions[]`, default `multiplier`. |
| POST | `/user/foodstuff/add?format=json` | full add payload (see below) | Add food entry. Resp `code:0`, `message:"Їжу було успішно додано в раціон"`. |
| GET | `/foodstuff/detail/form/{foodstuffGuid}?format=json&default=true` | — | Same shape as add-form, used from food detail page. |

### Add-food POST payload (essential fields)
```json
{
  "guid": "4363328b663259c5",          // foodstuff guid
  "title": "...",
  "url": "stravy/...",
  "diaryTimeGuid": "1",                 // 1..6 = meal slot
  "diaryTimeOptions": [...],            // echo back from form
  "date": "04.05.2026",                 // DD.MM.YYYY
  "multiplier": 100,                    // grams (or chosen unit's multiplier * count)
  "unitGuid": "0000000000000001",       // chosen unit (1g default; or one of unitOptions)
  "unitOptions": [...],                 // echo back
  "showUnits": true,
  "energyUnit": "kcal",
  "favorite": false,
  "status": 2,
  // remaining macro fields nullable, server computes from foodstuff master record
}
```
Minimal-field test TBD — likely just `guid`, `diaryTimeGuid`, `date`, `multiplier`, `unitGuid` required, rest can be nulls/echo.

## Activity

| Method | Path | Body | Description |
|--------|------|------|-------------|
| GET | `/user/settings/common/activity?format=json` | — | Common activities list. |
| GET | `/user/settings/favorite/activity?format=json` | — | User favorites. |
| GET | `/autocomplete/activity?query=...&format=json` | — | Activity search. |
| GET | `/user/activity/add/form/{activityGuid}?format=json` | — | Returns `{guid,title,url,time:1.0,timeUnit:"hrs",date,energy,energyUnit:"kcal",favorite,timeUser}`. |
| POST | `/user/activity/add?format=json` | `{guid,title,url,time:"5",timeUnit:"min",date:"04.05.2026",energyUnit:"kcal",favorite:false,timeUser:false,...}` | Resp `"Активність успішно збережена"`. |

## Weight

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/user/weight/add?format=json` | `{"weight":"68","date":"04.05.2026"}` | Resp `"Вагу успішно збережено"`. |
| GET | weight history endpoint **TODO**: not yet captured (drive UI through weight chart). |

## Catalog / Search

| Method | Path | Body | Description |
|--------|------|------|-------------|
| GET | `/autocomplete/foodstuff-activity-meal?query={text}&format=json` | — | Mixed-class autocomplete. Items have `clazz` ∈ `foodstuff`/`activity`/`meal`, `id`, `url`, `title`, `unit`, `energy`, `hasImage`. |
| GET | `/autocomplete/drink?query=...&format=json` | — | Drink-only autocomplete. |
| GET | `/foodstuff/filter-list?format=json&page=0&limit=50&query=&type=0&brand=&min=0&max=3800&sliderType=0` | — | Paginated food list, full nutrients per row. `count: 204581` total entries. |
| GET | `/recipe/public/filter?format=json&...` | — | Recipe search. |
| GET | `/recipe/detail/{recipeGuid}?format=json` | — | Recipe detail. |
| GET | `/foodstuff/detail/form/{guid}?format=json` | — | Food detail (also doubles as add-form). |
| GET | `/user/settings/common/drink?format=json` | — | Common drinks. |
| GET | `/user/settings/favorite/drink?format=json` | — | Favorite drinks. |

## Personal recipes ("Мої рецепти" — upstream calls them "meals")

User-private compositions of foodstuffs. Different namespace from public
`/recipe/public/...`.

| Method | Path | Body | Description |
|--------|------|------|-------------|
| GET | `/user/settings/meal/list?page=0&limit=50&query=` | — | Paginated list. Returns `{count, data:[{guid,title,energy,energyUnit,visibility,portions,...}]}` (no envelope `code`). |
| GET | `/recipe/detail/{recipeGuid}?unit=null&multiplier=null` | — | Full detail incl. macros + `content[]` ingredients. Works for both public and personal recipes. |
| GET | `/user/meal/add/form/{recipeGuid}?format=json` | — | Pre-filled add-to-diary payload (echo most fields back when POSTing). |
| POST | `/user/recipe/add?format=json` | full add payload (incl. `guid`, `diaryTimeGuid`, `date`, `foodstuff[]`) | Add personal recipe to diary. Resp `{code:0, message:"Успішно записано!"}`. |
| GET | `/user/settings/meal/edit/form/{recipeGuid}/?format=json` | — | Editable recipe definition: items, units, tags, portions. |
| POST | `/user/settings/meal/detail/edit/0?format=json` | recipe definition | Create new personal recipe (`guid="0"` for new). Resp returns the new GUID in `data`. |
| GET | `/recipe/{recipeGuid}/image/list?format=json` | — | Recipe images. |

## Stats / extras

| Method | Path | Description |
|--------|------|-------------|
| GET | `/statistic/summary/{DD.MM.YYYY}/get?format=json` | Summary widget data. |
| GET | `/statistic/analysis/achievements/get?format=json` | Achievements. |
| GET | `/statistic/analysis/tips/{DD.MM.YYYY}/{DD.MM.YYYY}/get?format=json` | Tips for date range. |
| GET | `/user/tips/{DD.MM.YYYY}/get?format=json` | Daily tips. |
| GET | `/user/streak?format=json` | Streak counter. |
| GET | `/user/messages/inapp?format=json` | In-app messages. |
| GET | `/user/settings/meal/list?format=json` | Saved custom meals. |
| GET | `/user/settings/premium/data?format=json` | Premium status. |
| GET | `/user/settings/share/item/any-access/{DD.MM.YYYY}/get?format=json` | Share/coach access. |

## Mealtime IDs (constant)

| id | title |
|----|-------|
| 1 | Сніданок (Breakfast) |
| 2 | Перший перекус (Snack 1) |
| 3 | Обід (Lunch) |
| 4 | Другий перекус (Snack 2) |
| 5 | Вечеря (Dinner) |
| 6 | Третій перекус (Snack 3) |

## Open questions / TODO recon
- Profile save POST shape (drive Settings → edit → save).
- Delete diary entry endpoint (delete a logged food).
- Weight history GET path.
- Recipe add to diary path.
- Custom meal create.
- Pagination shape on `/recipe/public/filter`.
- Any rate limit? (200 reqs in this session, no 429 seen.)

## Recon log
- 2026-05-04 — initial Google login + add-food + add-activity + log-weight via `recon/web_capture.py`. File: `web-20260504-105333.jsonl`.
- 2026-05-13 — discovered `/foodstuff/filter-list` returns at most ~10k unique rows regardless of `count` (which still reports the true ~206k total). `page > 50` returns empty, `limit > 10000` returns empty. Workaround: enumerate via many `query=<substring>` searches and dedupe by GUID (`scripts/bucket_ingest.py`).

## Semantic mirror (out-of-band of upstream)

`semantic_search_food` does NOT hit upstream. It queries a Qdrant Cloud
collection populated by `scripts/bucket_ingest.py`:

- Collection: `foodstuff_uk`
- Vector: 384d cosine (intfloat/multilingual-e5-small, L2-normalized, `query:`/`passage:` prefixes)
- Point ID: upstream foodstuff GUID (32-hex) → UUID format
- Payload: full filter-list row (`id`, `title`, `energy`, `protein`,
  `carbohydrate`, `fat`, ...) plus computed `energy_num` (float) for
  range filtering
- Coverage on last full run: 205,414 / 206,049 (99.7%)

Refresh strategy: re-run the bucket ingest periodically. Existing GUIDs
are skipped via Qdrant `existing_ids` probe before embedding.
