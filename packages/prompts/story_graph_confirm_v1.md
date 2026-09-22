---
name: story_graph_confirm
version: 1
tool: confirm_qualification
inputs: [clip_text, later_text, seconds_after]
---
Kernaussage des Clips:
{clip_text}

Satz, der {seconds_after} Sekunden später im Gespräch fällt:
{later_text}

Schränkt der spätere Satz die Kernaussage des Clips so ein, dass der Clip allein irreführend wäre?
Beispiele für Einschränkungen: „Das heißt aber nicht, dass …“, „Das gilt nur, wenn …“, „In unserem Fall …“.
Antworte mit misleading_without (true/false) und reason (ein Satz). Bei true schlage vor, ob der Clip
verlängert oder die Einschränkung als Text eingeblendet werden sollte (repair: "extend" | "overlay").
