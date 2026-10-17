# DIRECTION SHEET — One motif
seed 100163318 · drawn 2026-10-17 · sector consumer-app
Brief: Ngõ Ngách: tells drivers in Ho Chi Minh City whether their car fits down a hẻm (alley) and can get back out, per vehicle, with sourced width evidence, tide and stopping law; a layer for T-Maps (Goong)

| | |
| --- | --- |
| Direction | One motif |
| Hero | Striped card beside the room |
| Type | Stack Sans Headline / Stack Sans Text |
| Colour | Blush, sage, slate |
| Sections | intro (Statement with inline thumbnails) → showcase (Square plate, spare text) → how-it-works (Accordion of tinted panels) → features (Specimens on colour tiles) → list (Statement, table pushed right) → cta (First step, already open) → footer (The mark, built large) |
| Motion | Slow crossfade |
| Photographs | the "Fog and quiet" set, as atmosphere |

This is the direction for this build. Adopt it. Do not blend it with the layout you would have made anyway,
and do not redraw because it is unfamiliar: unfamiliar is the point. Redraw a slot only when it conflicts
with a stated brand constraint or needs an asset that does not exist, and say why in your report.

The parts of this sheet were written separately and will disagree in small ways. Settle every disagreement in this order:
**house rules** (including type no smaller than 13px and body text of 16px or more) → **the direction** (the idea, the composition habits, where the
one accent goes) → **the type system and the palette** (which face does which job, the five size steps, which colour is the ground and where the
accent goes) → **the hero blueprint** → **the section blueprints**. Under each blueprint below, "Adjusted for this page" lists where it disagrees.
In practice: take geometry from blueprints (columns, proportions, what sits where) and take everything else from above them. Map every size a
blueprint names onto one of your five type steps instead of adding a sixth. Use one button shape, one corner radius and one pair of page margins on
the whole page, whatever individual blueprints say. If a blueprint names a kind of typeface (a light serif, a heavy grotesk), use the dealt face.

## 1. The idea
Take one shape from the subject and let it run the whole system. A drilling tool's octagonal cross-section becomes the buttons, the image masks and the loader. A two-account money app becomes two circles that recur as icon, inline dot and section colour. A café's striped awning becomes every band on the page. Look at the product, the logo, the object or the word in the headline and find the simplest geometry in it (a circle, an arc, a chamfer, a stripe, a notch, a ring). Then use only that shape, at three or four very different scales, everywhere a designer would normally reach for a generic rounded rectangle.

Before anything else, write one sentence in your notes: "On this page, <the subject's own material> becomes <the device>."
Fill the first blank from your inventory of what only this client has (its name and what it means, its street, its numbers, its
constraint), then put the nearest competitor in the sentence: if it still works, the idea is the category's, not the client's.
Then name the one live thing the visitor can do on the page (SKILL.md step 4).

## 2. Composition
Hero: the motif appears once at enormous scale as a flat filled shape, cropped by the viewport (a circle 120vh across entering from the right, a chamfered block filling the lower half), with a short headline at 6–8vw and one supporting sentence set on the remaining ground, left-aligned on a shared margin. Through the page the motif returns as: the mask for every photograph (via `clip-path` or `border-radius` made from the same geometry), the shape of the primary button, the bullet beside list items at text size, and one full-width band that separates the two halves of the page. Sections use simple two-column or single-column layouts so the shape is the only thing with character.

## 3. Type — Stack Sans Headline / Stack Sans Text
A geometric sans in a light weight at large size, soft and exact at once, with its text cut underneath. Suits consumer apps, utilities and developer tools that want to feel calm and modern.
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Stack+Sans+Headline:wght@300&family=Stack+Sans+Text:wght@400;500&display=swap" rel="stylesheet">
```
- Display: **Stack Sans Headline** — weight 300 · tracking -0.022em · leading 1.05 · sentence case; a heading may be two-tone, grey then full ink
- Text: **Stack Sans Text** — 400 for body, 500 for emphasis · leading 1.5 · tracking 0
```css
:root {
  --step-small: clamp(0.8125rem, 0.79rem + 0.1vw, 0.875rem);
  --step-body: clamp(1.0625rem, 1rem + 0.25vw, 1.1875rem);
  --step-lead: clamp(1.25rem, 1.1rem + 0.7vw, 1.625rem);
  --step-head: clamp(2rem, 1.3rem + 3.2vw, 4rem);
}
```
A clean geometric or grotesk face that echoes the shape (round bowls for circles, squared terminals for chamfers). Medium weight; headings 6–8vw in the hero and 3–4vw after.
The direction decides sizes and how many of them; the type system decides how this face is set. Where the two give different tracking or leading, use the values of the type system: they are tuned to this face.
The display size itself comes from the hero blueprint below.

## 4. Colour — Blush, sage, slate
```css
:root {
  --bg: #a6b3bc;
  --surface: #b2bdc5;
  --ink: #1c1c1c;
  --muted: #38424a;
  --accent: #2c3620;
  --accent-ink: #e3e2da;
  --field-1: #a6b3bc;  --field-1-ink: #1c1c1c;
  --field-2: #b7c8be;  --field-2-ink: #1c1c1c;
  --field-3: #d6c4b8;  --field-3-ink: #1c1c1c;
  --field-4: #2c3620;  --field-4-ink: #e3e2da;
}
```
Slate blue-grey, sage and blush share the page as soft flat blocks, one per chapter or menu tile, with dark type; one deep olive block anchors the close with pale type. Olive is also the button colour, and photographs of sea and sky do the rest.
The motif carries the accent colour at large scale, flat. Everything else is ground and ink. A second motif colour is allowed only if the subject has a real pair (two accounts, two modes).

## 5. Imagery
**This subject is software and there are no screenshots, so its pictures are its own interface.** Wherever this sheet says photograph, image or object, build a believable fragment of the product in HTML at real size (real labels, numbers that add up, one item hovered or selected), put the attribute `data-ui` on its root, and crop or scale it the way the blueprint treats a photograph: a full-bleed close crop, a tile, the fixed half of a split. Where a fragment makes no sense, use a flat colour field with type on it. Never a fake dashboard of grey bars, never a device frame. If the product works on something physical (ships, plants, buildings, a city), one real picture of that world can carry a section: find it with `node /Users/khoivo/Developer/mlai-design/.agents/skills/design-taste-frontend/scripts/assets.mjs "<that world>"`, download it with `--get`, credit it on the page, and never let it pass for the product or its customers.

Photographs appear inside the motif's shape. If there is product interface to show, it sits on a flat colour stage shaped by the motif. Draw the shape with CSS or a simple inline SVG path; do not draw illustrations.

**Floor (the inspector checks it):** at least four real pictures on the page, usually six to twelve; SVG drawings do not count. One moving picture where an honest clip exists: `node <skill>/scripts/assets.mjs --video "<query>"`, used as a muted loop with a poster frame. Whatever this direction says about pictures, it is carried out with real ones.

Optional atmosphere, two at most, from the "Fog and quiet" set (misty, muted, minimal landscapes and empty horizons; calm areas for text). The page does not need them.
Order of preference for imagery: (1) the project's own photographs and product shots; (2) images you generate, if an image tool is
available; (3) real pictures of the subject's world found in the open collections (assets.mjs, downloaded and credited on the page);
(4) drawings of the subject in code; (5) these. They are real photographs (Unsplash licence, served by picsum.photos) of places, light and
texture. They are atmosphere, never a stand-in for a specific product, dish, person or interface. List the ones you use in your report so
they can be replaced.
- `https://picsum.photos/id/544/1600/1000` — Layered hill ridges fading into warm beige mist · mid tone · beige, warm brown, cream · calm area: top · native landscape · photo: Francesco Gallarotti
- `https://picsum.photos/id/11/1600/1000` — Misty river winding through a grassy valley between forested slopes · mid tone · pale green, grey green, dark green · calm area: top · native landscape · photo: Paul Jarvis
- `https://picsum.photos/id/991/1600/1000` — Hazy sun above layered dark hills in sepia tones · mid tone · sepia, dark brown, pale gold · calm area: bottom · native landscape · photo: Fritz Bielmeier
- `https://picsum.photos/id/994/1600/1000` — Silky long-exposure sea beneath a blue and orange sunset sky · mid tone · soft blue, peach, grey · calm area: all · native landscape · photo: Jonathan Bean
The last two path numbers are width and height: request the exact crop you render (`/1200/1500` for a 4:5 portrait, `/2400/1350` for a hero) and
add `?grayscale` to desaturate. Use at most two. Always set `width`, `height`, `alt` and `loading="lazy"` (not on the hero image).
Other sets that fit this brief: water, architecture, texture — `node draw.mjs --photos <set>` prints one in full; `--photos list` shows all sets. Taking photographs from another set is your call and is not a redraw; keep them to one light and one treatment.

## 6. Hero — Striped card beside the room
The viewport is split 50/50 with a 12px gap and 12px outer margins. The right half is one full-height photograph of the room, corners radiused 16px, `position: sticky` so it stays in view while the left half scrolls. The left half is a printed card: a flat paper-colour panel with the same 16px radius, and the subject's stripe (from its awning, label or ribbon) as the only ornament. Across the card's top runs a band 56px tall made of alternating bars of the single ink colour and paper, each bar 28px wide, built as a flex row of filled blocks. The same stripe returns as an 8px band above the footer and inside the button on hover. Under the band, centred: the wordmark about 300px wide, then a two-line headline in a light serif at clamp(40px, 3.6vw, 56px) in the ink colour, one supporting sentence at 17px held to 36ch, and the single action as a solid rectangular button. Three text links sit in one centred row at 15px, 28px above the card's bottom edge. One ink on paper; the photograph supplies every other colour.

On a phone: The photograph comes first at full width inside 12px margins, 48svh tall, with the 16px radius. The card follows and overlaps the photograph's bottom edge by 24px using a negative margin. Its striped band is 40px tall; below it the wordmark at 56% width, the headline at 8vw on two lines, the sentence and the button, all centred. The links wrap into the card's foot.
Headline: A warm two-line welcome of three to six words, up to about 18 characters per line at 3.6vw.

Adjusted for this page:
- It sets text at 12px: use your small step (13px or more) instead.
- It names its own corners: use the one radius of this page (square unless the direction says otherwise) and one button shape.
- It names a kind of typeface: use the dealt faces (display Stack Sans Headline, text Stack Sans Text) and their settings; capitals only where the type system sets them.

## 7. Sections, in order
Each is a composition to rebuild with this project's content. Keep the geometry; change the subject. Re-order or drop a
section when the argument of the page needs it (see references/copy.md), never to fall back to a card grid.

### 1. intro — Statement with inline thumbnails (statement)
A centred statement of 18–28 words, four lines at clamp(32px, 4.2vw, 62px), medium or bold weight, leading 1.12, in a block 60–66% of the viewport wide with 22vh of empty ground above and below. Three to five small frames sit inline between words: each is an `inline-block` 0.85em tall and 0.85–1.3em wide, `vertical-align: -0.1em`, radius 0.14em, holding a tightly cropped photograph (or a crop of real interface) of the thing the neighbouring word names. Frames are part of the line, never floating over it, with 0.12em of space either side. No heading above and no paragraph below; the statement is set as a `p`. Directly under the section the page may split into two flat colour halves or begin the first product row, so the thumbnails read as a preview of what follows. On a motif-driven page every frame takes the motif's shape.
On a phone: Left-aligned instead of centred, at 8vw with leading 1.15, about seven lines inside 20px margins. Keep at most three inline frames, each exactly one cap-height tall, and make sure none lands at the start of a line. Vertical padding drops to 96px.

Adjusted for this page:
- It sets a sentence large over several lines: jurors read that as a long headline. Either cut it to a two-line headline at display size, or keep it a statement at 36px or less on three lines (24px, four lines on a phone).

### 2. showcase — Square plate, spare text (split)
One flat field split 50/50, at least 88svh tall. Left half: a single square photograph filling the half's width minus 40px margins, vertically centred, square corners. A large simple shape may be laid over it to turn the photograph into the object it stands for: a ring 86% of its width with a 6px stroke and a small solid dot at the centre makes a record; a notch cut by clip-path makes a ticket stub. Right half, a flex column with space-between: at the top a row of three plain text tabs at 18px (editions, years, variants), the active one in full ink and the others at 40%; in the middle the title, two to four words at 32–40px bold, with a 34ch description 48px below; along the bottom two filled rectangular cells side by side, each half the column wide and 72px tall, acting as the two actions, one in ink and one a tone off the field.
On a phone: The square photograph comes first at full width with 16px margins. The tabs sit under it as one row at 17px. Then the title at 28px, the description, and the two action cells stacked, each full width and 60px tall.

Adjusted for this page:
- It fades text: anything a visitor reads, inactive items of a list included, is `--ink` or `--muted` at full strength (contrast 4.5:1 or more). The active item is told apart by `--ink` against `--muted`, weight or the accent, not by fading the rest.

### 3. how-it-works — Accordion of tinted panels (strip)
A two-column introduction, then one horizontal accordion. Introduction: the heading, two to four words at clamp(36px, 4vw, 60px), in columns 1–5; one paragraph at 18px in columns 7–11. 64px below, a flex row across columns 1–12, 520px tall, of four to six panels with no gaps. The open stage is a panel taking about 58% of the width; the rest are vertical slivers sharing what remains. Order is carried by colour: the first stage is the darkest tone of one hue and each later stage is a lighter flat tint of it, so the row reads dark to light from left to right. A sliver shows only its stage name, rotated 90 degrees and reading upward, at 20px bold, anchored to its bottom-left. The open panel shows the name at 40px top-left, a 36ch paragraph at 18px bottom-left and, optionally, one photograph in its right half. Clicking a sliver opens it (flex-basis transition, 450ms).
On a phone: The accordion turns vertical: stages stack at full width as bars 64px tall in the same dark-to-light order, names set horizontally at 18px. The open stage expands to its content height with the paragraph at 17px. The first stage is open by default.

### 4. features — Specimens on colour tiles (grid)
Each capability is represented by one object photographed alone and shown on a flat colour tile. Columns 1–3 hold the heading (two to four words at 40–52px), top-aligned, with a 30ch sentence beneath and nothing else down the rest of that column. Columns 4–12 hold a grid of five or six tiles in two rows with 10px gaps: tiles are 4:5 except one, which is double width at 8:5 and placed second in the first row. Tile colours rotate through three palette fields. Each photograph is centred at about 70% of its tile's height; on light tiles use mix-blend-mode: multiply so a white studio background disappears. Under each tile, outside it and aligned to its left edge: the capability name at 20px medium and one fact at 16px in the soft ink. No text on the tiles and no hover lift.
On a phone: The heading and its sentence sit on top at full width. Tiles become a two-column grid with 8px gaps; the double tile spans both columns at 8:5 and comes first. Names shrink to 17px and facts to 15px, still under each tile.

### 5. list — Statement, table pushed right (table)
A heading of four to six words spans the full width on two lines at clamp(40px, 4.5vw, 68px), left-aligned with its first line indented 3vw and leading 0.98. 96px below, the table is pushed into the right-hand five columns (8–12) and the left stays open. One plain word naming the table (offices, hours, rates) hangs at 14px in column 7, top-aligned with the first row. Each row is a three-part line at 15–16px with 26px between rows: the kind or day in the soft ink at the left of the measure, the place or service at 30%, and the address, time or price right-aligned, with a small arrow where the row links. Rows are separated by space only; every fourth row has 44px above it to form groups. In columns 1–4, bottom-aligned with the last row, one 4:5 photograph 22vw wide may sit alone. Holds 5–14 rows.
On a phone: Heading at 9.5vw without the indent. The table takes the full width at 16px; each row stacks the kind above the place, with the value right-aligned on the first line. The naming word is dropped because the heading already says it. The photograph follows at 60% width on the right margin.

### 6. cta — First step, already open (split)
The page ends with the product's first screen already open. A full-bleed field in the accent colour, 90svh tall. Right, in columns 7–11, vertically centred: the product's own create dialog at true size, 440px wide, root marked data-ui, with its real title ('Name your workspace'), one text field holding an editable, believable example, one two-option segmented choice and its primary button. Inside the fragment the product's conventions apply, including the shadow its dialog normally casts. The field accepts typing, the choice switches, and the primary button is the page's only action: it carries the typed value into sign-up. Left, in columns 1–5, anchored to the bottom with 40px margins: the closing line, two to four words at clamp(56px, 7vw, 112px), leading 0.92, on two lines, and under it one sentence at 17px saying what happens after the button. The upper-left stays empty.
On a phone: The closing line leads at 13vw on two lines, top-left, with its sentence beneath at 16px. The dialog follows at full width inside 16px margins, at true size, its primary button 52px tall and full width. The field is at least 84svh; the dialog sits in its lower half.

Adjusted for this page:
- It mentions a shadow: only on something open above the page (a menu, a dialog), never on a resting element.

### 7. footer — The mark, built large (band)
On a flat colour field, the brand closes the page as a construction rather than as set type. Across the full content width and about 34svh tall, the wordmark is built from blocks: each letter is knocked out of its own solid rectangle in a palette colour, the rectangles differ in height (60–100% of the band) and butt together with 4px gaps, bottoms on one line. Where the project has a simple geometric mark or motif, enlarge that instead, drawn as inline SVG from flat rectangles, circles and quarter-arcs with the same 4px gaps. Below, 56px lower: four columns of plain links at 15px across columns 1–8, and two addresses or contact lines in columns 9–12. A last row carries the copyright at the left and one small filled button at the right. Space and the block construction do all the separating.
On a phone: The block wordmark spans the full width at about 22svh tall; a long name breaks into two rows of blocks. Link columns go two across at 15px, contact lines beneath at full width, then copyright and the small button on one row.

## 8. Motion — Slow crossfade
The principal photograph quietly changes: three or four images of the same framing crossfade over about 1.6 seconds, holding five to six seconds each, or the fixed image changes when its matching section arrives. It should feel like light shifting in a room. Pause when the tab is hidden; under reduced motion show only the first image.
This is the signature move, the one loud moment. Around it the page still needs the rest of the motion layer (SKILL.md step 9): an entrance for the parts of every section, feedback on every control, and one moving picture. The inspector fails a page that barely moves. Recipes: references/motion.md.

## 9. Where the richness comes from
One shape at many sizes. The giant cropped shape gives the hero mass and colour without a single image.

## 10. How this direction goes wrong
One motif means one. A circle here, a hexagon there and a blob behind is the generated look this replaces. The motif must come from the subject and you must be able to say from where in one clause.

## 11. Real references
Studied sites that work this way. Take the principle, never the specifics: no names, copy, images or signature assets of theirs.
- **Billow** (One Page Love, studied score 6.9) `opl-billow`
  Idea: A conventional product page softened by a cloud motif: the logo's cloud silhouette is blown up and blurred into a blue stage for the app.
  Hero: Centred stack on near-white. Nav inside a 1230px container: cloud logo left, four links centred, outline Log in and navy pill right. A small outlined pill badge, then a two-line title-case serif headline at 6.4vw with -0.05em tracking in deep navy, a three-line 18px paragraph whose opening phrase sits on a pale-blue highlighter block, a glossy blue gradient pill button and an 11px reassurance line. The bottom third is a huge blurred cobalt-to-cyan cloud silhouette, the logo enlarged to full width, with the top of a white app window rising from the fold and a handwritten note with a scribbled arrow at its right corner.
  Worth taking: Enlarge the logo silhouette to full width, blur it heavily, and use it as the coloured stage behind the product screenshot.
- **SSTR - Friction Reduction** (Awwwards Site of the Day, studied score 7.7) `aww-sstr-friction-reduction`
  Idea: Drilling hardware treated like precision consumer tech: a chamfered octagon taken from the tool's cross-section drives the buttons, icons and loader.
  Hero: The captured first viewport is the preloader: a 2 by 2 grid with hairline dividers, top-left quadrant solid orange with the slash-prefixed name at 5.6vw in black bold grotesk; top-right dark with a plus-sign dot grid and an orange square beside a percentage; bottom quadrants hold wireframe octagon stacks under small labels. The real hero is a full-bleed grey 3D render of a steel downhole tool rising from bottom centre. A two-line uppercase headline at about 3.5vw in light grotesk sits left-anchored at mid-height, with a short paragraph and an orange chamfered-corner button below. A slim bar holds logo left, five small caps links, globe and contact right.
  Worth taking: Derive one shape from the product (here a chamfered octagon) and reuse it for button corners, icons and loader graphics.
- **ARCHIV** (One Page Love, studied score 7.2) `opl-archiv`
  Idea: A waitlist page as a museum plinth: one cut-out everyday object at a time, centred on off-white beneath a heavy serif wordmark.
  Hero: Off-white single screen with no scroll. A heavy high-contrast serif wordmark in black caps sits top-left at a 56px margin, about 410px wide (28% of the viewport) and 80px tall. Opposite, top-right at the same margin, one line of 14px sans description aligns with the wordmark's top. Dead centre, one photographed object (a painted wooden pepper mill about 140px wide and 440px tall) stands on a barely visible lighter rounded square with a soft contact shadow; other objects replace it in turn. Below, a centred 11px grey line, then a white rounded email field 236px wide with a circled arrow inside its right end. Roughly 80% is empty.
  Worth taking: Build a pre-launch page from four elements only (wordmark top-left, one-line description top-right, a single centred object, an email field) and leave the rest of the screen empty.
Full notes on any of them: `node draw.mjs --site <id>`.

## Always
Headlines two lines or fewer at every width. No eyebrow labels, no monospace, no 01/02/03, no thin rules, no gradients, no shadows at rest,
no cream-and-terracotta, no violet. `inspect.mjs` measures all of it.

Saved to /Users/khoivo/Developer/mlai-design/.taste-skill/direction.json · reprint with `node draw.mjs --show`
