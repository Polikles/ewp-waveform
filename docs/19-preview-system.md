# 19 — Preview System

## Asset preview

Preview uses the real rendering pipeline over a short interval; it is not an unrelated approximation.

Controls should include start time and duration. Grouped tracks use the same source-time interval.

Each source still produces its own preview asset.

## Preview composition

A later convenience feature may combine generated preview assets into one non-canonical scene for one/two/three speakers.

Preview template may control background, positions, sizes, spacing, and optional branding placeholders.

Template changes do not affect canonical waveform render identity.

## GUI readiness

Preview operations should be exposed through application-level models so a future GUI does not duplicate CLI behavior.
