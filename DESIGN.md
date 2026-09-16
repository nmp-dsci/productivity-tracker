# DESIGN.md — productivity-tracker visual system

Modelled on simplychocolate.dk (requested 2026-09-16). Applies to the React
app, every `.lavish/` review page, and any generated report.

## Tokens (`frontend/src/styles/tokens.css`)

| token | value | use |
|---|---|---|
| `--bg` | `#EFEFEF` | page ground |
| `--paper` | `#FFFFFF` | alternating sections, cards, tables |
| `--ink` | `#1C1C1C` | text, primary button, single-series bars |
| `--ink-2` | `#3E3E3E` | secondary text |
| `--muted` | `#6B6B6B` | captions, eyebrows |
| `--line` / `--line-2` | `#CFCFCF` / `#DDDDDD` | hairlines |
| `--wine` | `#6E2A2A` | one hero / feature panel per screen — a surface, never a series colour |
| `--black` | `#0F0F0F` | footer, code blocks |
| `--magenta` `--gold` `--green` `--cocoa` | `#B4386E` `#C9A24A` `#6E8A2E` `#4A2C22` | multi-series data, in that order |

## Type

- Headings: **Barlow Condensed 700**, uppercase, `letter-spacing: .04–.06em`
  (stand-in for the site's proprietary condensed face). H1 44–84px, H2 30px, H3 20px.
- Eyebrow: Barlow Condensed 600, 12px, `.18em` tracking, uppercase, muted.
- Body: **Inter** 400/500, 14px, line-height 1.55.
- Big numbers: condensed 700 at 56px (stat strip) / 30px (in-app KPI row).
- Mono: system monospace for ids, paths, code.

## Shape & surface

- `border-radius: 0` everywhere. No box-shadows.
- Cards are cells in a 1px hairline grid (`gap:1px; background: var(--line)`),
  not floating boxes.
- Sections alternate `--bg` / `--paper`, 72px vertical rhythm, 1400px max width.
- Every section opens centred: eyebrow → H2 → one-sentence lede.
- One full-bleed split hero per top-level view: image / data-art left,
  wine panel right with centred copy and ghost buttons.

## Controls

- Primary button: black fill, white condensed caps, `.14em` tracking, trailing `→`.
- Secondary: 1px outline ghost (inverts to white on wine).
- Tabs: condensed caps with a 2px underline on the active tab.
- Tags: hairline-boxed 11px caps. Variants: `yes` (ink fill), `rec` (wine fill),
  `decide` (gold fill), `later` (muted).
- Inputs: native, 1px ink border, square.

## Data

- Single-series bars: ink. Multi-series: magenta → gold → green → cocoa.
- Diagrams: ink boxes, wine for stores, magenta for push/webhook edges,
  dashed hairlines for regions.
- Pair every effort metric (tokens, $) with an output metric (commits,
  deploys, pages) in the same row — never show effort alone.

## Implementation notes

- No component library (MUI/DaisyUI defaults fight the look). Small set in
  `frontend/src/ui/`: `Btn`, `Tag`, `Eyebrow`, `StatStrip`, `HairlineCards`,
  `SplitHero`, `KpiRow`, `ShipLog`.
- Fonts via Google Fonts (Barlow Condensed 600/700, Inter 400/500/600) with
  system fallbacks; the demo image must render without network.
- Reference implementation: `.lavish/s00_implementation-plan.html`.
