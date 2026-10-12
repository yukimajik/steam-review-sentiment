# Steam Review Sentiment Dashboard

## Rules
- Don't assume. If anything is unclear (requirements, design choices, data formats), ask me before writing code.
- Before starting each phase, give me a short plan and wait for my OK.
- Keep it simple. Don't add features I didn't ask for.
- Verify your work: actually run the code and tests and show me the real output. Never say something works without running it.
- Never make up numbers. Any stats must come from real runs.
- Handle errors properly (API failures, empty results, bad input, rate limits).
- Keep secrets in a .env file and make sure .env is in .gitignore.
- At the end of each phase, summarize what changed and suggest a commit message.

## Learning doc
Maintain docs/HOW_IT_WORKS.md and update it after every change. Include:
- What each file does
- How data flows through the app, step by step
- Why each design choice was made, and what the alternatives were
- Key concepts explained simply
- Likely interview questions about this project, with good answers


DISTILLED_AESTHETICS_PROMPT = """
<frontend_aesthetics>
You tend to converge toward generic, "on distribution" outputs. In frontend design, this creates what users call the "AI slop" aesthetic. Avoid this: make creative, distinctive frontends that surprise and delight. Focus on:

Typography: Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial and Inter; opt instead for distinctive choices that elevate the frontend's aesthetics.

Color & Theme: Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes. Draw from IDE themes and cultural aesthetics for inspiration.

Motion: Use animations for effects and micro-interactions. Prioritize CSS-only solutions for HTML. Use Motion library for React when available. Focus on high-impact moments: one well-orchestrated page load with staggered reveals (animation-delay) creates more delight than scattered micro-interactions.

Backgrounds: Create atmosphere and depth rather than defaulting to solid colors. Layer CSS gradients, use geometric patterns, or add contextual effects that match the overall aesthetic.

Avoid generic AI-generated aesthetics:
- Overused font families (Inter, Roboto, Arial, system fonts)
- Clichéd color schemes (particularly purple gradients on white backgrounds)
- Predictable layouts and component patterns
- Cookie-cutter design that lacks context-specific character

Interpret creatively and make unexpected choices that feel genuinely designed for the context. Vary between light and dark themes, different fonts, different aesthetics. You still tend to converge on common choices (Space Grotesk, for example) across generations. Avoid this: it is critical that you think outside the box!
</frontend_aesthetics>
"""