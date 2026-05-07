---
name: tablycja
description: Calorie / nutrition tracking on tablycjakalorijnosti.com.ua via the `tablycja` MCP. Trigger when the user asks to log/track/edit food, drinks, weight, activity, calories, macros, recipes, "сьогоднішній раціон", or similar nutrition-tracking phrases — OR when they mention specific foods + amounts + meal times together. Skip for general nutrition questions that don't touch the user's diary.
---

# Tablycja MCP — efficient usage

You are working against `tablycjakalorijnosti.com.ua` (a Ukrainian-language calorie tracker) through these MCP tools:

**Read:**
- `get_active_user()` — auth probe; id, email, sex, lang.
- `get_profile()` — height, weight, target, AMR, daily energy + macro goals.
- `get_day(day)` — diary for a day. Returns 6 meal slots; each item carries `id` (the diary entry GUID — needed for edits).
- `get_summary(day)` — totals + macro breakdown vs goals.
- `get_food_detail(food_id)` — full nutrients + unit options for a foodstuff GUID.
- `list_my_recipes(query?, page?, limit?)` — user's saved recipes ("Мої рецепти").
- `get_my_recipe(recipe_id)` — recipe ingredients + macros.
- `get_diary_entry(entry_id)` — editable form of a logged item.

**Search:**
- `search_food(query, limit)` — fast autocomplete; titles + kcal/100g only. **No macros.**
- `search_food_with_macros(query, limit, min_energy?, max_energy?)` — full DB w/ per-100g protein/carb/fat/fiber. **Slower but useful when picking by macros.**
- `search_activity(query, limit)` — activities autocomplete.

**Write:**
- `log_food(food_id, grams, meal, day)` — add a foodstuff entry.
- `log_activity(activity_id, minutes, day)` — add activity.
- `log_weight(weight_kg, day)` — log body weight.
- `log_recipe(recipe_id, meal, day, exclude_ingredients?, scale_ingredients?)` — log a personal recipe; optionally drop or scale ingredients before posting (server recomputes).
- `edit_diary_entry(entry_id, exclude_ingredients?, scale_ingredients?, meal?)` — modify an already-logged item.

## Operational rules

### 1. Always Ukrainian for searches
The food DB is localized to UA. **Translate the user's term to Ukrainian first**, then search. Do not search English or other languages unless the user explicitly typed it. Examples:
- "apple" → search "яблуко"
- "fried chicken breast" → "куряча грудка смажена"
- "salmon" → "лосось"

### 2. Date handling
Always use **ISO `YYYY-MM-DD`**. Convert relative refs:
- "today" / "сьогодні" → today's date.
- "yesterday" / "вчора" → today − 1.
- "Friday" / "п'ятниця" → most recent Friday.
- DD.MM.YYYY also accepted by tools but stick to ISO for clarity.

### 3. Meal slot mapping
Tools accept `breakfast|snack1|lunch|snack2|dinner|snack3` OR `1..6` OR Ukrainian names. Choose by context:
- 06:00–10:30 or "сніданок" → `breakfast`
- 10:30–12:30 or "перекус ранковий" → `snack1`
- 12:30–15:30 or "обід" → `lunch`
- 15:30–17:30 or "перекус після обіду" → `snack2`
- 17:30–22:00 or "вечеря" → `dinner`
- 22:00+ or "нічний перекус" → `snack3`
- If the user gives a clock time, pick the slot bracketing it.
- If unclear, pick by the current local time (assume Europe/Kyiv).

### 4. Picking the right food from search results
Search returns multiple variants. Score by:
1. **Exact title match** > prefix match > substring.
2. **Generic over branded** ("Курка тушкована" beats "Курка — Auchan").
3. **Plain over composite** ("Хліб житній" beats "Хліб з маслом і сиром").
4. **Reasonable kcal/100g** (sanity vs USDA ballparks, e.g. apple ~50, chicken ~165).
5. If still ambiguous → ask user to disambiguate w/ a 3-row list.

For macro-aware queries ("low-carb chicken", "high-protein snack"), prefer `search_food_with_macros` and rank by the relevant macro field.

### 5. Logging workflow (default)
```
search_food_with_macros("<UA query>", limit=5)
  → pick id by rules above
log_food(food_id=id, grams=N, meal=<slot>, day=<ISO>)
get_summary(day=<ISO>)   # confirm new totals to the user
```
Show the picked food's title + kcal so the user can spot a wrong pick.

### 6. Editing logged entries
User says "remove X from the Y I logged" / "actually I had only half":
```
get_day(day) → find item where title matches Y → grab item.id
edit_diary_entry(entry_id=item.id, exclude_ingredients=["<UA name>"])
# or
edit_diary_entry(entry_id=item.id, scale_ingredients={"<UA name>": 0.5})
# or move slot
edit_diary_entry(entry_id=item.id, meal="dinner")
```
Upstream recomputes macros server-side.

### 7. Recipes
- "log my cocktail" / "Сніданок чемпіона" → `list_my_recipes(query="...")` → pick id → `log_recipe(recipe_id, meal, day)`.
- "without banana" → pass `exclude_ingredients=["Банан"]`.
- "half portion of avocado" → `scale_ingredients={"Авокадо Хасс": 0.5}`.
- Match ingredient names exact (case-insensitive). If user gave English, translate to UA.

### 8. Reporting back
Daily summary fields (`get_summary`) come pre-formatted by upstream:
- `items[code=total]` = energy goal vs actual (with comma-separated thousands like "2,063").
- `itemsDynamic[0]` = macros (Білки, Вуглеводи, Жири, Волокна).
- Water tracked under title `Питний режим`, unit `л`.
- Target weight shown but actual in kg.

Quote upstream Ukrainian labels verbatim where the user used Ukrainian; otherwise translate. Always include both raw + percent: `1677 / 2122 kcal (79%)`.

### 9. Error handling
- `Upstream redirect (302 → /login); session expired. Re-bind the connector.` → user must Remove+Add the connector in Claude. The server attempted `/login/create` w/ stored creds and got rejected. Most often = user changed pwd on tablytsia.
- `non-JSON response` → upstream returned HTML. Treat as session issue.
- Envelope `code != 0` → surface upstream message verbatim (e.g. "Твій пароль невірний").
- If `get_active_user` itself fails → don't try other tools; tell user to re-bind.

### 10. Avoid waste
- Don't call `search_food_with_macros` when the user already gave you a `food_id`.
- Don't call `get_food_detail` after `search_food_with_macros` unless the user asks for a deeper nutrient breakdown — the search already includes core macros.
- Batch reads when possible: a day report = `get_day` + `get_summary` (parallel).
- Don't refetch profile each turn; cache it in conversation context.

### 11. When data is missing
- User asks for a food that's hard to find → tell them, suggest creating a personal recipe ("Мої рецепти" on the website). Server can't currently create recipes via MCP (TODO endpoint capture).
- Stats over time — partially supported. Use `get_summary` per day; aggregate yourself in conversation if user asks for a week.

### 12. Privacy posture
The bearer token Claude holds is **password-equivalent**. Don't echo it. Don't print full tool responses verbatim if they contain `password` or `cookies` fields (the active-user upstream payload contains a md5 password hash — strip it before showing).

## Quick patterns

**"What did I eat today?"**
```
date = today_iso()
[get_day(date), get_summary(date)] in parallel
→ render: each meal w/ items + kcal; totals + macros + water
```

**"Log 150g chicken breast for lunch"**
```
search_food_with_macros("куряча грудка", limit=5)
pick best (e.g. "Куряча грудка" plain, ~165kcal/100g)
log_food(id, grams=150, meal="lunch", day=today_iso())
get_summary(today_iso())  # confirm
```

**"Add my Avocado-toast recipe to breakfast, no banana"**
```
list_my_recipes(query="Авокадо")
pick id where title=="Авокадо-тост"
log_recipe(recipe_id=id, meal="breakfast", day=today_iso(),
           exclude_ingredients=["Банан"])
```

**"Edit my breakfast — I only had half the avocado"**
```
day = get_day(today_iso())
find item w/ title="Авокадо-тост" → item.id
edit_diary_entry(entry_id=item.id, scale_ingredients={"Авокадо Хасс": 0.5})
```

**"Set today's weight to 67.8"**
```
log_weight(weight_kg=67.8, day=today_iso())
get_profile()  # show updated context if relevant
```

**"How am I doing this week against macros?"**
```
for day in last 7 days: get_summary(day)
aggregate energy + protein/carb/fat actuals vs goals
render compact table; flag days >100% or <50%
```
