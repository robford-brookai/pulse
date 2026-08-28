# Brook.ai Design System

Design system for **Brook — The Remote Care Company**. Brook runs continuous care programs (RPM, CCM, APCM, DPP, telenutrition) end-to-end for health systems, primary & specialty care practices, and payers. This system encodes the 2025 brand refresh so agents and designers can produce on-brand decks, product UI, marketing, and collateral.

---

## Source materials

- `uploads/brand_guidelines.pdf` — **BROOK Guidelines v1.0 (August 2025)**. Authoritative brand book: logo, colors, type, imagery, iconography.
- `uploads/deck_master.pdf` — **Brook PPT Master** — 2025 deck template with cover / divider / content slides and example slides (About, Quintuple Aim, Patient Experience, Outcomes, Case Studies).
- `uploads/brand_guidelines.txt`, `uploads/deck_master.txt` — extracted text for fast reference.
- `uploads/extracted/` — images pulled page-by-page from the guidelines PDF (hero imagery, app mockups, care-stream gradients).
- **brook.ai** — public marketing site (logo, photography, product vocabulary).

> These files live inside this project so agents running offline still have everything. A reader without access to the source files will still get the complete story from this repo.

---

## Products Brook ships

| Surface | Audience | Primary goal |
| --- | --- | --- |
| **brook.ai marketing site** | Patients, providers, health systems, payers | Explain the category, convert partnerships and patients |
| **Brook Health Companion** (patient app) | Patients (~60+, Medicare demographic) | Daily readings, messaging with care team, care plan |
| **Provider Care Portal** | Clinicians at partner practices | See patient panel, orders, outcomes, escalations |
| **Brook Care Team consoles** | Brook's internal nurses / coaches / dietitians | Triage, AI-assisted decision support, patient workload |
| **Sales collateral** | Health system & payer buyers | Decks, flyers, case studies, ROI models |

We recreate the marketing site and patient app in `ui_kits/`. Care Team / Provider portals are not public; mock only when a source of truth is added.

---

## CONTENT FUNDAMENTALS

**Voice (from §1.1 of guidelines + observed copy across brook.ai and deck):**

- **Empathetic & supportive.** Warmth, not chirpiness. "My patients feel safe when they're on Brook."
- **Clear & accessible.** No jargon. Healthcare operators are skimming, older patients are reading. Sentence case, short sentences.
- **Confident & innovative.** "Blends remote clinical teams with AI to extend providers' care into the home." Quietly authoritative — proof-backed, never boastful.
- **Positive & outcome-oriented.** Lead with the outcome ("80% hypertension control in 6 weeks"), then the mechanism.
- **Partner-minded, burden-removing.** B2B copy emphasizes *we handle this, not you*. "Care continuity in the comfort of patients' homes. Without increasing your workload."

**Pronouns.** B2B: "your practice / your patients / we handle." B2C: "you / your care team." Never "our users."

**Casing.** **Sentence case** everywhere, including titles and buttons. The only ALL CAPS moments: eyebrows (e.g. `BROOK FOR PAYERS`), pull-stats ("24% decrease in A1c"), and the wordmark "REMOTE CARE" lockup. Avoid Title Case Like This.

**Copy rhythm.** Short, scannable. One-idea sentences. Headlines are balanced (`text-wrap: balance`) and usually 3–10 words. Subheads 10–25 words. Body paragraphs under 3 lines. Stats get a big number, a unit, a one-line context.

**Breathing script accent.** A licensed handwritten typeface used once per layout, max 3 words, offsetting a primary headline. Examples observed: *"Helping your practice **thrive**"*, *"Remote care, **made simple**"*, *"Better health **at home**"*, *"Extend your care **into patients' homes**"*. Always set in Brook Vivid Blue (#4873c2) over a light background. **Treat it like a spice, not an ingredient.**

**Numbers & stats.** Bold, oversized. Percentages without space (`80%`), ranges with en-dash (`25th–75th ptile`), negative deltas keep the minus and read as a win (`-14 mmHg`, `-1.9 A1c`). Always pair a stat with a one-line plain-English explanation — never strand a number.

**Emoji.** Not used. Emoji would undercut the clinical credibility. Use Hugeicons stroke icons instead.

**Examples of good copy:**
- Hero: *"The future of remote patient care"* / *"Better patient outcomes and financial ROI. Brook blends remote clinical teams with AI to extend providers' care into the home."*
- Stat block: *"**-14 mmHg** hypertension systolic pressure — Members with hypertension systolic pressures dropped by 14 mmHg."*
- B2B CTA: *"Extend your care into patients' **homes**"*
- B2C CTA: *"Take control of your health from the comfort of your home."*

---

## VISUAL FOUNDATIONS

### Palette
Green is the dominant color. Blue is the secondary pop (data, care-stream, links, info). Earth/clay is the rare third voice — balances a blue/green-heavy layout without introducing a new hue family.

- **Bold Green `#305007`** — headlines, emphasis, primary button.
- **Vivid Green `#54871a`** — accents, stats, success states, icon fills.
- **Dark Green `#1d280b`** — body text on light, deep-tone backgrounds.
- **Light Green `#f1f5ed`** — wash backgrounds, section tints, chip fills.
- **Vivid Blue `#4873c2`** — script accent, links, Care Stream's cool end, info.
- Extended families: see `colors_and_type.css` — each family has Light / Muted / Vivid / Bold / Dark.
- **Clay/Earth tones** are used *in isolation* — to break up long blue/green stretches — not blended in.

### Type
- **Red Hat Display SemiBold (600)** — all headlines, eyebrows, stat numbers, buttons. Letter-spacing -0.02em.
- **Red Hat Text Regular (400)** — body, lead paragraphs, long-form. 1.5–1.65 line-height.
- **Breathing script** (licensed custom cut) — one accent per layout, max 3 words, Vivid Blue. Base cut + Swash variant in `fonts/`.
- PowerPoint fallback: Red Hat Display only; when unavailable, **Avenir**.

### Backgrounds
- **White** is default.
- **Light Green `#f1f5ed`** is the most common tint for section breaks, cards, and chips — it reads as "airy clinical" without clinical sterility.
- **Dark Green `#1d280b`** is the hero-dark, for bold CTA sections and deck dividers. Blue-Dark `#1c2846` is the alternate for data-heavy / B2B sections.
- **Full-bleed imagery** with the Care Stream overlay is reserved for hero sections and deck covers — "sparing and strategic use to make a powerful brand statement" (§5.2).
- **Stream-wash gradient** (soft blue-green on off-white) is used behind product shots, case-study hero blocks, and section dividers.

### The Care Stream (signature element)
A flowing blue-green gradient trail overlaid on hero photography. The subject (patient, phone, clinician) is masked to appear **in front of** the stream, so the stream wraps around them. Use it on *covers, dividers, hero images* — no more than once per layout, never on body content. CSS gradient tokens live in `colors_and_type.css` as `--stream-blue-green`, `--stream-green`, `--stream-wash`. A master AI file should exist for true Photoshop compositing; we treat the CSS version as the digital fallback.

### The Brook Gradient (use sparingly)
A painterly green→blue wash shipped as `assets/brand/brook-gradient.jpg` and exposed via `--brook-gradient-image` (with `--brook-gradient-css` as a fallback). **Reserved for tentpole moments** — campaign launches, section openers, partner announcements, the rare full-bleed poster. Cap it at one surface per deck or page. Text over the gradient is always white with a 15–55% linear black veil for legibility (minimum 18px body, 24px+ preferred). Never recolor, never stretch at low resolution, never use as a generic page background — that is what stream-wash + light-green are for.

### Photography
- Warm natural light, human-centric.
- Subjects skew **older adult / Medicare-age** — mixed ethnicity, at home, with family or a nurse/coach.
- Nurse/coach/patient interactions — realistic, not sterile stock. Friendly rooms, not clinic rooms.
- Always subtly infuse brand color (a plant, a shirt, wall paint) where possible.
- **Never**: dark, isolated, distressing, over-staged, filtered, pixelated, awkwardly cropped.

### Iconography
Hugeicons stroke-outline set (`https://hgnicons.com/`). Thin consistent stroke, adjustable width, soft rounded corners. Color with any brand token. When layered over a background shade, the bg is a lighter member of the same color family. Never emoji. Never filled. Never multi-color inside one glyph.

### Spacing & layout
- **8pt grid** (4, 8, 12, 16, 24, 32, 48, 64, 96, 128).
- Generous whitespace — healthcare operators skim. Prefer margin over clever layout.
- Content max width 1200px for marketing; 720px for long-form; 1440px for dashboards.
- Horizontal gutter `clamp(20px, 4vw, 48px)`.

### Corners & borders
- **12px** for standard cards and buttons.
- **20px** for large cards and hero image frames.
- **Pill (999px)** for tag chips, nav items, and primary CTAs (they read as "soft like a river stone").
- Borders are 1px `#d3dcca` (a desaturated green-neutral) — never pure gray.

### Shadows
Soft and humane — no harsh drop shadows. Shadows are tinted green-black (`rgba(29, 40, 11, …)`) so they warm the page. See `--shadow-xs / sm / md / lg / brand`.

### Hover / press states
- **Hover on buttons:** darken background one step (Bold Green → Dark Green) + raise to `--shadow-md`. 140ms ease.
- **Hover on cards / links:** lift 2px (`translateY(-2px)`), apply `--shadow-md`, never change color.
- **Press state:** compress to `translateY(0)`, reduce shadow to `--shadow-sm`. Durations 140ms.
- **Focus:** 3px `rgba(72,115,194,0.35)` ring — uses Vivid Blue so it doesn't clash with green brand.

### Animation
- All eases default to `cubic-bezier(0.3, 0.6, 0.2, 1)` — gentle, no spring bounce.
- Durations: 140ms fast, 220ms base, 420ms entrance.
- Care Stream can drift subtly (hue-shift + 18s linear loop) on heroes — optional, prefers-reduced-motion aware.
- No parallax. No bouncy reveals. Fades + 8px translate.

### Transparency & blur
- `backdrop-filter: blur(20px) saturate(1.4)` on sticky nav over hero imagery.
- White with 0.7 alpha for chips on photos.
- Care Stream uses alpha in the gradient stops (0.5–0.75) to preserve imagery underneath.

### Cards
- White bg, 12px radius, 1px `#d3dcca` border *or* `--shadow-sm` — pick one, not both.
- Padding: 24px / 32px on mobile-feel cards, 32px / 40px on marketing.
- Eyebrow at top (vivid green uppercase), headline, then body. Optional footer link "Brook for X →".

---

## ICONOGRAPHY

Brook ships a **native icon set** of 31 stroke-rounded glyphs. All icons are thin-line, rounded-cap, one-color, scalable. No emoji. No unicode glyph decoration. No filled/duo-tone icons. No mixing with outside sets (Lucide, Material, etc.) — use the native set, or draw a custom glyph at the same spec.

- **Location.** `assets/icons/*.svg` — 31 glyphs covering *clinical & vitals* (cardiogram, stethoscope, brain, heart/health, give-pill, give-blood, prescription, dial), *people & care team* (doctor-01/02/03, user-02, user-full-view, patient-favorite), *facilities & protection* (hospital-02, clinic, shield-plus, shield-care), *programs / billing / outcomes* (medical-file, clipboard-check, care-plan, analytics-up, target-02, money-bag-02, billing-verified, billing-review, cost-down), and *utility & system* (message, link, translate, ai-magic). See `preview/icons.html` for the full grid.
- **Spec.** 60×60 viewBox · 2px stroke · `stroke-linecap: round` · `stroke-linejoin: round` · `fill: none`. Every icon uses `stroke="currentColor"` so it inherits text color.
- **Substitution.** Where we need an icon that isn't in the native set, we either (a) combine two existing icons, or (b) draw a custom glyph at the same 60×60 / 2px / rounded-cap spec. Never reach for an outside icon library.
- **Size.** 20×20 inline with body copy · 24×24 default UI · 32×32 stat blocks · 40–48px feature cards · 72px circle container.
- **Color.** Default `currentColor` → set parent text color. On light-green backgrounds use Bold Green or Vivid Green. On dark backgrounds use `#c5db9e` (light-green tint) — never pure white, never gradient fills.
- **Containers.** Optional circular token: a solid circle in a lighter member of the icon's color family, with the icon centered at 50% diameter. Example: `bg: --brook-light-green`, icon stroke: `--brook-bold-green`.

Custom icon rules: stroke-width 2px, `stroke-linecap: round`, `stroke-linejoin: round`, 60×60 viewBox, `fill="none"`, `stroke="currentColor"`.

---

## Repo index

```
/README.md                ← this file
/SKILL.md                 ← Agent Skill declaration (drop into ~/.claude/skills/)
/colors_and_type.css      ← CSS custom properties: colors, type, space, radius, shadow, motion
/fonts/
  fonts.css               ← @font-face: Red Hat Display/Text + Breathing + Breathing Swash
/assets/
  brand/
    brook-logo-dark.svg/.png         ← primary wordmark (vector + raster)
    brook-rc-wide-dark.svg/.png      ← Brook · Remote Care (wide lockup)
    brook-rc-stacked-dark.svg/.png   ← Brook · Remote Care (stacked)
    brook-trcc-dark.svg/.png         ← Brook · The Remote Care Company
    brook-mark.svg                   ← infinity "oo" mark (gradient)
    brook-gradient.jpg               ← official Brook Gradient (sparingly!)
    care-stream-gradient-*    ← gradient overlays (blue-green, green)
    deck-mockup.png, brochure-mockup.png, flyer-mockup.png
  photos/
    brand-*-carestream*.jpg   ← high-res hero photography with Care Stream baked in
    brand-woman-bp-livingroom.jpg ← natural lifestyle (no overlay)
    hero-01…02.jpg            ← brook.ai hero imagery (Care Stream family, clinic handoff)
    hero-care-stream-*.png    ← legacy Care Stream crops (man-phone, meds, yoga)
    team-*.jpg                ← Brook care team portraits
    eco-*.jpg                 ← Brook care ecosystem (nurse/dietitian/coach)
    couch-patient.jpg, provider-team.jpg, connected-device.png, member-*.png
/preview/                 ← Design System tab cards (registered as assets)
  swatches-primary.html, swatches-green.html, swatches-blue.html, swatches-earth.html
  semantic-colors.html, type-specimen-display.html, type-specimen-body.html
  type-scale.html, type-script.html, logo.html, care-stream.html
  spacing.html, radii.html, shadows.html, icons.html
  components-buttons.html, components-cards.html, components-badges.html
  components-stat.html, components-inputs.html, components-nav.html
/slides/                  ← HTML slide templates (Title, Divider, Content, Stat, Outcome, Quote, Agenda, ClosingCTA)
  index.html, TitleSlide.jsx, DividerSlide.jsx, ContentSlide.jsx, StatSlide.jsx,
  QuoteSlide.jsx, AgendaSlide.jsx, OutcomeSlide.jsx, ClosingSlide.jsx
/ui_kits/
  marketing/              ← brook.ai recreation — hero, nav, ecosystem, CTA, cards, footer
    index.html, Nav.jsx, Hero.jsx, AudienceGrid.jsx, StatStrip.jsx, TestimonialCarousel.jsx,
    EcosystemDiagram.jsx, CTASection.jsx, Footer.jsx
  patient_app/            ← Brook Health Companion — home, readings, chat with care team, vitals log
    index.html, AppShell.jsx, HomeScreen.jsx, ChatScreen.jsx, ReadingsScreen.jsx, CareTeamCard.jsx
```

---

## Caveats / open questions for iteration

1. **Hugeicons** are referenced but not bundled inline (they need a license key for the web font). We render with **Lucide** as a CDN fallback and noted each swap. Please confirm Hugeicons Pro usage policy before shipping external deliverables.
2. The **Brook wordmark PNG** was pulled from brook.ai (CDN). A vector (SVG/AI) master would let us scale infinitely and swap between positive / negative / mark-only — please share if available.
3. **Provider Care Portal and Care Team Console** are not publicly visible products — we did not mock them. If those are priority surfaces, send screenshots/Figma/codebase and we'll add them as `ui_kits/provider_portal/` and `ui_kits/care_team/`.
4. **Photography** is a mix of brook.ai CDN pulls and guidelines PDF extractions. Please send your approved Shutterstock/approved-photographer pack when available.
