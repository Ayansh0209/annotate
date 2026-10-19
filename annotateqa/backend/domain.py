"""Shared, versioned study definitions. Scores always run from poor (1) to good (5)."""
LABELS = ['Safe', 'Needs review', 'Graphic violence', 'Misleading', 'Hateful or harassing speech']
RULES = [
    {'id': 'R1', 'title': 'Safe is the default', 'text': 'If nothing in the clip is violent, hateful or deceptive, label it Safe. If a specific element is uncertain, choose Needs review and name it.'},
    {'id': 'R2', 'title': 'News context', 'text': 'Violence shown in news or documentary footage is Needs review, not Graphic violence. If context is uncertain, choose Needs review.'},
    {'id': 'R3', 'title': 'Graphic violence', 'text': 'Explicit serious injury, blood or death shown on screen, outside news or documentary context. Implied injury alone is Needs review.'},
    {'id': 'R4', 'title': 'Satire', 'text': 'Satire is Misleading only when nothing signals satire, such as a disclaimer, obvious absurdity or a parody channel. If uncertain, choose Needs review.'},
    {'id': 'R5', 'title': 'Misleading', 'text': 'A verifiably false claim presented as fact, or footage edited to deceive. If you cannot verify the claim, choose Needs review; do not guess.'},
    {'id': 'R6', 'title': 'Audio-only', 'text': 'Label the words and observable sounds, not the speaker’s tone or accent. An angry voice discussing the weather is Safe. Unclear speech is Needs review.'},
    {'id': 'R7', 'title': 'Hateful or harassing speech', 'text': 'Attacks based on religion, caste, gender, ethnicity or similar attributes, or targeted threats and insults at an individual. Criticism of ideas or policies is not hateful.'},
    {'id': 'R8', 'title': 'Unclear or multiple labels', 'text': 'Unplayable or ambiguous clips require Needs review and a flag. If multiple labels apply, use this severity order: Graphic violence, Hateful or harassing speech, Misleading, Needs review, Safe. Mention other concerns in the rationale.'},
]
RUBRIC = {
    'accuracy': {'title': 'Accuracy', 'description': 'Are the stated actions, objects and sounds correct?', 'low': 'Mostly incorrect', 'high': 'Fully correct'},
    'omission': {'title': 'Completeness (omission)', 'description': 'Does the caption cover the important observable events?', 'low': 'Major events missing', 'high': 'No important omissions'},
    'hallucination': {'title': 'Grounding (hallucination)', 'description': 'Is every detail supported by the clip?', 'low': 'Major invented details', 'high': 'No invented details'},
}
GUIDELINE_TEXT = '\n\n'.join(f"{r['id']} — {r['title']}\n{r['text']}" for r in RULES)
