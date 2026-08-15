# Safety Boundaries

Version: 1.0.0
Applies to: all current and future modules in this skill.

## Purpose

These boundaries prevent the skill from turning risk signals into performance advice when the user may be unsafe.

## Risk classes

### Green

- No red-flag symptoms.
- Normal planning, comparison, and summarization are allowed.

### Yellow

- Mild soreness, fatigue, heat stress concerns, or small uncertainty about readiness.
- The module may suggest conservative adjustments, rest, hydration, or easier effort.
- The module must not claim diagnosis.

### Red

Treat the output as a stop condition when any of these appear:

- Chest pain, fainting, altered consciousness, or severe breathing difficulty.
- Persistent high fever or clear whole-body illness.
- Suspected fracture, inability to bear weight, or acute severe pain.
- Severe dehydration, heat illness, confusion, or uncontrolled vomiting.
- Race staff, medical staff, or official safety personnel instruct the athlete to stop.

## Required behavior at red level

- Stop outputting pace targets, intervals, finish-time predictions, or push strategies.
- Recommend urgent medical or race-staff evaluation when appropriate.
- Separate immediate safety advice from performance judgment.
- Do not convert a red signal into a training tweak.

## Required behavior at yellow level

- Prefer recovery, reduced load, or conservative pacing.
- Explain uncertainty clearly.
- Avoid diagnostic language such as "you definitely have" or "this proves".

## Competition priority

1. Official race safety instructions.
2. Medical personnel instructions.
3. Athlete safety and immediate stabilization.
4. Skill output.

If official safety says stop, the skill stops.

## Output rules

- Do not present medical advice as a replacement for professional care.
- Do not bury safety warnings inside long performance text.
- When risk is red, the first visible answer must be the safety response.
- When risk is uncertain, say so explicitly instead of pretending confidence.

## Module notes

- `itra_public_runner` can classify blocked access, but it must not reinterpret health signals.
- Future training and weather modules must use these boundaries before they issue any recommendation.
