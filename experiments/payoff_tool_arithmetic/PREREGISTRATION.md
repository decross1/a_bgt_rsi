# Prospective public-goods payoff tool diagnostic

This is a small instrument study of Gemma's ability to use a deterministic
calculator and then finish an arithmetic answer. It does not test strategy
repair, theory novelty, trading value, or production promotion. The direct and
tool conditions expose the same game rule, actions, focal seat, question, and
answer format. The tool condition additionally exposes one registered native
OpenAI function. Its use changes the serving template and permits a second
model turn, so any contrast is a **tool-interface and arithmetic-scaffold
bundle**, not an isolated causal effect of calculator arithmetic.

## Frozen questions and control

There are six paired inputs: three games crossed with focal seats 0 and 1.
Each paired input has one direct condition and one tool condition, for twelve
scheduled conditions. The games use four binary contribute-all actions:

| Game | Endowment per seat | Contribution multiplier | Actions in seat order 0,1,2,3 | Contributors | Focal seat 0 | Focal seat 1 | Joint material payoff |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| G1 | 3 | 3/2 | 0,1,0,0 | 1 | 33/8 | 9/8 | 27/2 |
| G2 | 7 | 5/2 | 1,0,0,1 | 2 | 35/4 | 63/4 | 49 |
| G3 | 11 | 7/3 | 1,0,1,1 | 3 | 77/4 | 121/4 | 88 |

The action vectors are not any of the three A or three B payoff-representation
vectors or the earlier pilot's arithmetic example. The full game inputs also
change endowment and multiplier from the earlier 5-and-2 panels. This is a
fresh task panel, not a new seed on a frozen answer. The independent control is
`bench.agentic_game_theory.calibration.payoffs`, evaluated with exact rational
arithmetic: a contributor keeps zero endowment, a retainer keeps the full
endowment, and all seats receive `multiplier * endowment * contributors / 4`.
The requested final form is bare JSON with exactly the two string keys
`{"focal":"<canonical rational>","total":"<canonical rational>"}`. A canonical
rational is a reduced integer or reduced fraction with positive denominator;
floats, numeric JSON fields, fences, prose, extra keys, and a `sum` alias fail
the output contract. No worked answer or oracle tuple appears in either model
request.

## Paired intervention and fixed ceiling

Within each game/seat pair, the direct and tool arms use the same Gemma model
identity, explicit thinking-off policy, temperature 0, top-p 1, top-k 64,
disclosed game and arithmetic question, and first-request seed. The tool arm
adds only the instruction to invoke the available function first; this
instruction and the later tool-result turn are part of the intervention. The
arm order alternates across the six
pairs before any result is read. The frozen manifest must bind each task's
exact messages, policy, seed, model/admission receipt, source hashes, order,
per-turn output budget and timeout, and evaluator/host deadlines. Every model
completion has a maximum of 256 output tokens and a 25-second timeout. The direct
arm permits one model completion. The tool arm permits at most one native tool
call followed by one final model completion. Thus at most six direct plus six
tool-first plus six tool-final model completions can issue: **18**. The direct
and tool-final answer budgets should be equal; any additional tool-emission
budget and second-turn context are declared treatment overhead. A 600-second
evaluator cutoff and at most 25 seconds per model request bound the model-call
ceiling to 450 seconds, leaving 150 seconds for tool execution and journaling.
The resident supervision and exact-restoration bounds are separate from this
ten-minute evaluator cutoff: ordinary parent supervision is bounded by 1,500
seconds with a 600-second internal restoration reserve, and a distinct
300-second emergency parent recovery may follow, for at most 1,800 seconds of
host supervision. A shortened per-request timeout, partial schedule,
or cutoff produces an incomplete result, not a passed twelve-condition panel.

The only calculator is a code-owned deterministic function taking the four
actions, endowment, and multiplier numerator/denominator. It returns **only**
`{"shared_return":"<canonical rational>"}`, with a single exact rational string equal to
`multiplier * endowment * contributors / 4`. It must not return contributor
count, focal payoff, joint payoff, per-seat payoffs, a recommended action, or
an oracle explanation. The native function name is `shared_return`; its
required JSON arguments are exactly `actions` (four binary integers), `E`
(positive integer), `m_num` (positive integer), and `m_den` (positive integer),
with no extra keys. The model must select the tool arguments from the
question and still derive the focal retained-endowment term and the joint
retained-endowment term for its final answer. Arguments are schema-checked and
graded for exact equality to the frozen task before tool execution. Wrong but
schema-valid arguments are `wrong_args`: no tool is executed and the final
model slot is causally skipped. No argument is silently corrected. The tool
response is appended as an actual `role=tool` turn with the parsed call ID.

The tool arm succeeds as tool-assisted only after the first response has
`finish_reason=tool_calls` and contains exactly one native parsed
`assistant.tool_calls` function call to the registered name,
with valid exact task arguments, and the second response supplies the strict
final JSON answer. A prose claim that the calculator ran, a JSON-shaped imitation
in `content`, or a manually inserted result is not a tool call. Inline Gemma
markup missed by the server parser is a distinct `parser_miss` observation;
this version does not synthesize or rescue such calls after the fact. A bypass,
unknown/multiple tool call, a parsed call with `finish_reason=length`
(`tool_incomplete`), invalid arguments, timeout, or transport error
remains in the six scheduled tool-condition denominator. A condition whose
first tool request fails has no issued final request, with that unissued slot
reported explicitly. No retries or post-result prompt/policy changes are
allowed within this registered panel.

## Independent admission and report

Every issued model request stores the exact request hash, raw private SSE,
transport metadata, parsed final/tool fields, and finite timing under private
permissions. The public rows bind those raw files by SHA and expose only
closed status codes, actual model completion count, tool-use and argument
counts, strict-shape validity, focal correctness, joint correctness, and both
correctness. The independent grader replays the raw SSE and the deterministic
tool from the exact recorded arguments, checks each tool-result request turn,
regenerates the six frozen questions and rational oracle values, and
recomputes every count. It admits the panel only after the resident admission,
worker/supervisor identity, memory monitor, watchdog, and exact restoration
also pass. Scheduled denominators are six per arm and twelve overall even when
a model response is absent; issued completion requests are counted separately
up to eighteen. Per-pair descriptive differences are reported without an IID
or population claim. A failed or unrun arm cannot be described as improved.
