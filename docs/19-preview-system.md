# 19 — Preview System

## Asset preview

Preview uses the real rendering pipeline over a short interval; it is not an unrelated approximation.

Controls should include start time and duration. Grouped tracks use the same source-time interval.

Preview defaults to **30 fps** so operators can judge look before a slower/larger **60 fps** production render. 60 fps remains a canonical option and a different render identity.

Each source still produces its own preview asset.

## Preview composition

A later convenience feature may combine generated preview assets into one non-canonical scene for one/two/three speakers, matching the Iuris et Logos boards:

- one speaker: centered wave, pale cyan;
- two speakers: left/right waves (cyan / blue) plus caption cards;
- three speakers: guest on top (yellow), two hosts below (cyan / blue).

Preview template may control background (`#2F474F` slate teal), positions, sizes, spacing, logos, and caption placeholders.

Template changes do not affect canonical waveform render identity.

## GUI readiness

Preview operations should be exposed through application-level models so a future GUI does not duplicate CLI behavior.
