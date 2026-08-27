# UI/UX Direction — from "gloomy dashboard" to a calm, official-feeling console

## Why the current UI reads as gloomy, specifically

Not a vague impression — three concrete things in `app/frontend/index.html` compound into it:
1. **A five-step dark stack** (`--bg-base` → `--gray-950`, up through `--bg-elevated` → `--gray-600`) with muted borders sitting on top of it. Heavy dark-on-dark with low-contrast borders is what makes a UI feel murky rather than "premium dark."
2. **Eight competing accent hues** — primary orange, plus success/warning/danger/info/teal/violet/pink, each with its own dim/mid variant. No single color reads as *the* brand color because none of them is used often enough to register. This is what makes it feel busy and unfocused rather than considered.
3. **Outfit**, the current display font, is one of the most common typefaces in AI-generated and templated dashboards right now. It's not a bad font, but it's not doing any work to make this feel like *your* product.

None of this is a UI/UX opinion problem — it's a token-discipline problem. The fix is fewer, more deliberate choices, not more decoration.

## The one real decision this direction makes: light, not dark

Your current dashboard-dark-mode-plus-one-accent look is also, at this point, one of the two or three things almost every AI-generated interface reaches for by default. Doubling down on dark mode would polish the current direction, not change it.

The people using this are applying for scholarships, updating Aadhaar details, checking pension status — often on a shared or older phone, often in daylight, often already a little anxious about a government process. A light, high-contrast, unmistakably calm interface serves that better than a dark cockpit aesthetic borrowed from developer tools, and it's a more specific, defensible choice for this exact audience than either the current look or "premium dark mode." (A dark mode toggle is a fine *later* addition — it's just not the lead direction.)

## Token system

**Color — six named values, used consistently, nothing else:**

| Token | Hex | Use |
|---|---|---|
| `--paper` | `#F4F5F6` | Page background — a cool, neutral off-white. Deliberately *not* warm cream: warm cream + serif + terracotta is its own overused AI-default look, and this brief calls for something cooler and more official-feeling anyway. |
| `--surface` | `#FFFFFF` | Cards, panels — pure white against the slightly gray paper gives depth with zero shadow-stacking. |
| `--ink` | `#1B1F2A` | Primary text. Near-black with a cool undertone, not pure `#000` — softer to read at length. |
| `--ink-muted` | `#5B6472` | Secondary text, captions, timestamps. |
| `--indigo` | `#2C4472` | The one brand color. Buttons, links, active states, focus rings. Deep and official — the color of a passbook or a letterhead, not a startup gradient. |
| `--marigold` | `#C8862B` | The *only* other accent, spent on exactly one thing: the moment the agent hands control back to the user. Warm, has real cultural resonance (marigold is used across Indian ceremony and everyday life for auspiciousness and attention), and is nowhere near any shade of terracotta. |

Two quiet status colors, used only where they mean something specific — not decoration:
- `--verified` `#2F6F4E` (muted forest green — a field verified against the live page)
- `--attention` `#A23B3B` (muted brick red — a real error, never a decorative badge)

That's it. Six colors, two of them load-bearing. Compare to the current eight-hue-plus-variants system — the discipline *is* the premium feeling.

**Type — three faces, each with one job:**
- **Archivo** (700/800) — display only: the product name, big numerals, section eyebrows. Used sparingly, which is what makes it land when it appears.
- **IBM Plex Sans** (400/500/600) — everything else: body copy, labels, buttons, navigation. Chosen partly because the Plex family has genuine Devanagari support, which matters the day this needs Hindi labels.
- **JetBrains Mono** (400/500) — kept from the current build, it's a good choice — reference numbers, URLs, timestamps, the trace log. Anything that's data, not prose.

**Spacing, radius, motion:**
- Generous whitespace over dense packing — the current UI's cramped stat bar and tightly-stacked panel are part of what reads as heavy.
- Small, consistent radius (`8px` cards, `6px` controls) — enough to feel soft, not enough to feel bubbly.
- One deliberate motion moment, not ambient animation everywhere: the trace log entries write themselves in sequentially, like a ledger being filled in real time. Hover states are quiet (a border-color shift, not a lift-and-shadow). The handoff moment (below) gets a single calm fade-and-settle, never a bounce or a pulse — this is a bureaucratic-anxiety-reducing tool; nothing on screen should feel urgent unless it actually is.

## Component patterns, mapped to your real screens

**Portal directory** (currently `index.html`'s main view): centered content column rather than edge-to-edge, product name in Archivo with a single plain-language line under it, a search bar that's the visually dominant element on the page (it's the only real input most users need), filter pills as quiet outlined pills rather than filled saturated chips, and a 3-up card grid where each card is a white surface with a hairline `--border`, the portal name in Plex Sans 600, and category as a small quiet label — not a colored badge. Delete the five-stat counter bar or fold it into one quiet line; five bold numbers competing for attention on load is noise before the person has done anything.

**The live-automation view** (currently the resizable side panel in `index.html` / `automation.html`) is the actual product and deserves to be the best-designed screen, not an afterthought panel: a browser-chrome-framed screenshot on one side (a thin top bar with three dots and a URL pill communicates "this is a real browser acting for you," which matters for trust) and a vertical trace ledger on the other, each entry a quiet numbered row showing what the agent observed, reasoned, did, and verified — mono caps for the four sub-labels, current step with a subtle indigo rule, completed steps quiet and slightly muted rather than every row shouting for attention.

**The handoff moment** (CAPTCHA, OTP, payment, final confirmation) is the signature element of this whole redesign, because it's the one moment that most directly embodies the thing you've said matters most: the agent isn't hiding what it's doing, and it's not trying to do the human's job for them at the moments that count. Give it a distinct card with a marigold rule (not a filled alarm-colored banner), plain first-person-plural copy that says exactly what's needed ("Enter the CAPTCHA shown below, then continue" — never "Action required!!"), and one clear button. It should feel like the agent respectfully stepping back and handing over the pen, not an error state.

**Vault / personal-details entry** (not yet built per the implementation plan, Phase 2) — same system: white surface cards, Plex Sans labels above each field, indigo focus rings, and — given what's being collected — visibly reassuring, specific copy near any Aadhaar/PAN/bank field about where it's stored and that it never leaves the device unencrypted, rather than a generic privacy-policy link. This is a place where the interface can actively build the trust the rest of the product depends on.

## What to avoid

- Don't reach for a warm-cream-plus-serif-plus-terracotta look to "warm up" the light theme — that's the *other* overused AI default, just as recognizable as dark-mode-plus-one-accent.
- Don't add a third accent color. The discipline of two is what makes marigold mean something when it appears.
- Don't use numbered step markers (01/02/03) decoratively — the trace ledger is a genuine sequence, so numbering it is honest; a features list or card grid is not a sequence, and numbering it would be decoration pretending to be information.
- Don't animate everything that can be animated. The ledger writing itself in is the one moment; hover states elsewhere should be nearly silent.

## Accessibility and localization, given the actual audience

- Body text no smaller than 15px, generous line-height (1.5+) — some users are on older phones with worse screens and worse eyesight than a typical SaaS demographic.
- All state communicated by color is also communicated by text or icon (verified/error/needs-you), never color alone.
- Visible keyboard focus everywhere, and every interactive element reachable by keyboard — this matters more than usual here, since some users will be on assistive tech and this product's whole premise is *lowering* the barrier to government services, not adding a new one.
- Plex Sans's Devanagari coverage means the same type system carries a future Hindi (or, with a suitable pairing, other Indic-script) version without a redesign.

## What's in the attached mockup vs. what extends the same system

The mockup file builds two screens end to end — the portal directory and the live-automation trace view with a handoff moment — because those are the two screens that carry the whole visual identity. Portal detail, vault entry, and the confirm-before-submit review screen aren't built pixel-for-pixel, but they're direct applications of the same six colors, three fonts, and card/rule/quiet-hover patterns above — nothing about them needs a new decision, just the same system applied to different content.
