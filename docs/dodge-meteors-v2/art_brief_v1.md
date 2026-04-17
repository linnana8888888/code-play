Dodge the Meteors — Art Brief (v1)

Color Palette (3–5)
- Deep Space: #0B0F1E
- Accent (near-miss, thrusters): #22D3EE
- Meteor Body: #FF7A1A
- Damage/Warning: #FF3B30
- UI Light/Neutral: #E6F1FF

Sprite Style
- 2D, clean low-res sprites on a 16px grid; flat shading with a simple 2-tone ramp (no soft gradients) for clarity.
- 1px outer outline or subtle hard-drop shadow for readability on dark backgrounds.
- Meteors: irregular chunky silhouettes with 2–3 crater details; two-tone orange; 4–6 rotational frames for motion.
- Ship: compact arrow-like silhouette with clear forward direction; two-tone body; thruster plume as a 2–3 frame sprite anim (avoid heavy alpha particles).
- Use one shared sprite atlas (≤1024×1024) for all sprites to minimize draw calls.

UI Font Suggestion
- Primary: Rajdhani SemiBold (600–700) for score, wave, and buttons — sci-fi feel with high numeric legibility.
- Alternatives: Orbitron or Oxanium; system fallback: Segoe UI, Roboto, Helvetica Neue, sans-serif.
- UI treatment: high-contrast light/cyan on dark; minimal glow; thin 1px stroke for text if needed.