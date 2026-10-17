# Ngõ Ngách design system

**Principle: the map is the product.** The base map fills the screen, our layer (fit, flood, route, walk) is the only strong colour on it, and the UI floats over it as quiet cards. Every result leads with a decision ("Dừng đón ở X, đi bộ 2 phút"), then the reason, then the evidence one tap away.

Based on Google Maps / Material 3 patterns drivers already know (directions card, chips, bottom sheet, layer button), with our own restrained palette so the semantic colours dominate.

## Tokens (`tokens.css`)

| Group | Tokens | Use |
|---|---|---|
| Neutrals | `--n-0 … --n-900`, roles `--surface`, `--text`, `--text-2/3`, `--outline` | all chrome |
| Brand | `--brand` (road-sign teal), `--signal` (orange: destination, walk) | identity, primary buttons |
| Route | `--route` (blue), `--route-standard` (dark dotted) | our drive vs the source-aware OSM/Goong reference route |
| Fit for this car | `--fit-fits/tight/no/unknown/blocked` + `-tint` | alley lines, tags, check icons; always paired with text or a dash pattern |
| Water vs this car | `--flood-low/risky/over`, `--flood-tint` | flood layer, tide timeline, flood verdicts |
| Type | Be Vietnam Pro for everything: `--font-ui` (body) and `--font-display` (decisions, numbers, heavier weights); sizes `--fs-11 … --fs-36` | full Vietnamese; tabular numerals on |
| Space / shape / depth | `--s-1…8` (4 pt), `--r-xs…pill`, `--e-1…3` | hairline + soft ambient shadows only |

## Components

Primitives (`base.css`, `ui.tsx`): `.btn` (primary / tonal / ghost / outline / sm), `.icon-btn` (raised for map tools), `.chip` + `ChipMenu`, `.field`, `Segmented`, `Tag` (tone = ok / warn / bad / muted / water / brand), `.tabs`, `.popover`, `.skel`, `.bar`.

Product components (`../components`): `Directions` (start/destination, my location, swap, vehicle / purpose / time chips), `Verdict`, `LiveStrip` (live data collection), `StopRow` (+ checks), `StandardRouteContrast` (source-aware OSM/Goong reference route), `EvidencePanel` (tabs: width, photos, flood, lookup), `TideTimeline` (drag the stay over the tide curve).

## Writing

- Lead with what to do, sentence case, no uppercase labels (they clip diacritics).
- Vietnamese numbers: decimal comma (`vn()`, `metres()`, `vnt()` for server text).
- Never say "Không ngập" (not flooded); say it is within this car's limit ("Trong ngưỡng xe").
- Law is cited, never advised.
