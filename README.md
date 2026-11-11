# ShiritoriBench

ShiritoriBench is a closed-book benchmark in which language models play competitive Japanese Shiritori. Models return one hiragana noun per turn; a deterministic referee validates moves against a pinned JMdict-derived SQLite vocabulary.

The project includes pilot runners, deterministic reference bots, offline analyses,
and a buildless preliminary website. No environment or package installation is
required for the static website or offline Python analysis.

## Preliminary website / GitHub Pages

`web/` contains the complete static site: a real-data pilot comparison, replayable
game transcripts, an interactive kana atlas with discount controls, and methodology
notes. Results are explicitly preliminary; there is no invented Elo ranking.
Thinking A/B aliases are merged by recorded model/thinking configuration.
Infrastructure-error games do not contribute wins, losses, tokens or validity.

To refresh the public data after new saved pilots and offline analyses:

```sh
python3 scripts/build_site_data.py
```

This uses an explicit allowlist. It exports final words, dictionary meanings,
frequency estimates, outcomes, aggregate usage and analysis diagnostics, but
**not** private reasoning, raw API responses, prompts, request bodies or keys.
It validates matching vocabulary hashes and rejects duplicate match IDs.
Do not use the older `export_results.py` to overwrite this site's v2 payload;
that script belongs to the previous leaderboard skeleton.

Preview from the project directory:

```sh
python3 -m http.server 8856 --bind 127.0.0.1 --directory web
```

Then open `http://127.0.0.1:8856/`. Opening the HTML as a `file://` URL will not
load its JSON snapshot. No Node build, framework, server backend, API key or
paid hosting is needed. Optional Google Fonts fall back to system fonts offline.

The included `.github/workflows/pages.yml` uploads **only `web/`**, never the
project root. After putting this project in a GitHub repository:

1. Set **Settings → Pages → Build and deployment → Source → GitHub Actions**.
2. Push the website and workflow to `main`, or run **Publish benchmark website**
   manually in the Actions tab. If your default branch is not `main`, adjust
   the workflow branch first.
3. Use the Pages URL returned by the successful deployment. Relative asset paths
   support repository subpaths such as `/shiritori-bench/`.

The repository contains both the benchmark implementation and the website.
Only `web/` is deployed to GitHub Pages; the Python benchmark runs separately
on your machine or cluster. The workflow serves the checked-in public snapshot;
it does not download corpora, run paid pilots, or require repository secrets.
API keys, raw game logs, downloaded corpora, and generated dictionary/frequency
files are excluded from Git. Keep `.env` untracked.
See [GitHub's custom Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

JMdict-derived readings and English gloss extracts retain their EDRDG attribution
and CC BY-SA 4.0 terms; TUBELEX attribution and BSD-3-Clause information are linked
in the site's methodology. Frequency matching, kana aggregation and filtering are
our transformations, not claims of endorsement by either data source.

## Repository layout

```text
config/models.json             Initial OpenRouter model roster
config/experiment.json         Openings, repetitions, limits, and bot roster
prompts/player.txt             Canonical model prompt
scripts/build_vocabulary.py    JMdict XML to SQLite importer
src/shiritori_bench/           Referee, reference bots, and OpenRouter client
tests/test_bots.py              Reference-player behavior tests
web/                           Static LisanBench-inspired leaderboard shell
data/                          Pinned-source manifest and vocabulary documentation
```

## Intended flow

1. Download and pin a JMdict XML snapshot separately.
2. Build a filtered SQLite vocabulary with `scripts/build_vocabulary.py`.
3. Run matches through the OpenRouter-compatible client.
4. Export aggregate results to `web/data/results.json`.
5. Serve or publish the static `web/` directory.

## Algorithmic reference players

The package contains two deterministic, vocabulary-aware bots. They are
reference opponents rather than entries in the closed-book LLM leaderboard:

- `GreedyBot` chooses the safe word that leaves the opponent the fewest safe
  replies. It breaks ties by JMdict common-word status and then normalized
  reading.
- `SearchBot` uses iterative-deepening negamax, alpha-beta pruning, a
  transposition table, and a fixed node budget. `SearchBot-10K` examines at
  most 10,000 states per move. If a depth cannot be completed within the
  budget, it retains the result from the deepest completed depth.

Both bots avoid words ending in `ん` unless every available move ends in
`ん`. With the same vocabulary, game state, node budget, and code version,
they always return the same answer.

The referee uses `data/processed/referee-vocabulary.sqlite`, which retains all
eligible noun readings. Algorithmic players use the deliberately smaller
`data/processed/bot-vocabulary.sqlite`, built with `--common-only`, so they do
not weaponize obscure dictionary vocabulary against closed-book models.

## Running matches

### Seeded FrequencyBot self-play (offline)

```sh
python3 scripts/run_frequency_bots.py
python3 scripts/run_frequency_bots.py --threshold 0.1 --alpha 0.5 --trials 3 --seed 17
```

The default runs three seed pairs in both player orders: six games from `か`,
with a 2,000-submission cap. Each game gets fresh, independent local RNGs.
The bot's fixed vocabulary contains safe noun readings with unambiguous
TUBELEX frequency at least 1 per million (currently 7,878 readings). It samples
unused words with probability proportional to `frequency ** alpha`, alpha 1
by default. Alpha 0 provides a uniform diagnostic. There is no lookahead or
strategy bonus. This vocabulary policy is provisional, not human calibration.
`--frequency-policy lower` uses lower matched counts instead of excluding all
readings with ambiguous contributions; it never sums ambiguous upper counts.

The bot never repeats a word, submits an unmeasured rescue word, or chooses
a word ending in `ん`. It returns PASS when its own safe pool is exhausted.
The full referee may still have words, so `PASS_WITH_LEGAL_MOVE` is an expected
baseline-vocabulary loss, not an infrastructure failure or a full-dictionary
dead end. Compare word submissions separately from the terminating pass.

Each run creates a new `results/bot-selfplay/` directory containing `games.txt`,
`matches.jsonl`, `summary.txt`, `summary.json`, `manifest.json`, and the actual
fixed word/frequency pool in `vocabulary.json`. The manifest includes seeds,
seat order, vocabulary/frequency/code hashes, settings and Python version.
Turn metadata records remaining candidate count, frequency mass and selected
word probability. Match files are appended after each game. Reproduction means
the same choices and outcomes for the same seeds, inputs, ordered states and
implementation—not identical timestamps or run IDs. These runs are deliberately
separate from paid pilots and the public LLM comparison. No API key is needed.

### Retrieval and memory ablations (offline)

```sh
python3 scripts/run_cognitive_bots.py
```

This runs a 180-game round robin including self-play: four profiles, three
openings (`か`, `さ`, `ず`), three seed pairs and both seat orders. All use the
same measured vocabulary and frequency exponent; no strategy or search bonus.

- FrequencyBot: perfect unused-word access, as above.
- RecallBot: at most 10 frequency-weighted retrievals per turn; perfect repeat
  recognition, but **no used-word prefilter before retrieval**.
- MemoryBot: unlimited retrieval (each matching candidate at most once per
  turn), with noisy recognition of older played words.
- RecallMemoryBot: combines the 10-retrieval budget and noisy recognition.

Memory defaults: the last 12 global played words are recognized exactly.
For older words, recognition probability is
`0.2 + 0.8 * 2 ** (-(age - 12) / 40)`. Thus recognition at age 52 is 60%,
not 50%; the half-life applies to recognition probability above the 20% floor. This is a
simple exploratory probability rule, **not a fitted ACT-R model or a validated
human-memory model**. Recognition trials and word retrieval use separate local
seeded RNG streams. Retrieved-but-rejected words do not rehearse their traces.

The full chronological history remains available. Memory profiles intentionally
apply noisy recognition to latent last-seen traces rather than filtering by
the exact used-word set. Forgotten repeats can be submitted and lose under
the independent referee. All profiles still know word legality and avoid `ん`
perfectly; spelling mistakes and rule-attention lapses are not modeled.

Settings can be changed with `--attempts`, `--recent`, `--half-life`,
`--memory-floor`, `--alpha`, `--threshold`, `--openings`, `--trials` and `--seed`.
The current defaults were selected before examining tournament results; do not
interpret short games as evidence of human realism. These are mechanisms to
compare, not difficulty levels calibrated against people or LLMs.

Each run writes a fresh `results/cognitive-bots/` folder with full `games.txt`,
short `examples.txt`, append-only `matches.jsonl`, per-game diagnostic JSONL,
summaries, seeds/settings/code hashes in `manifest.json`, and the fixed
`vocabulary.json`. Failures distinguish repeated words, retrieval-budget passes
and actual baseline exhaustion. Win rates exclude self-play; capped games
remain unfinished. The LLM prompts and public website data are not modified.

### Move-quality analysis

Run the offline analysis against the frozen dictionary, frequency index and
all saved pilot games:

```sh
python3 scripts/analyze_moves.py
python3 scripts/analyze_moves.py --word かっぱ --required か --used かさ さる
python3 scripts/analyze_moves.py --threshold 0.1 --alpha 0.5 --skip-matches
```

No model calls, packages or environment setup are needed. Each run creates a
new `results/move-analysis/` directory with `summary.txt` (readable results),
`analysis.json` (settings, source hashes, kana profiles and sensitivity tests)
and `moves.jsonl` (individual move diagnostics). Existing game files are not
modified. The default compares thresholds 0.1, 1 and 10 occurrences per million,
log and linear mass rewards, and discounts 0.5, 0.85 and 0.95.

Implemented measures include:

- Full-dictionary and frequency-covered safe reply counts and frequency mass.
- Reply entropy, effective candidate counts, top-1/top-5 concentration.
- Incoming/outgoing word-count and frequency-mass ratios, attack accessibility
  (distinct initials of words ending at a kana), two-kana attack accessibility,
  self-return counts/probability, and shares of potential replies ending in `ん`.
  These are exploratory adaptations of structural features in
  [Murata et al. (2007)](https://www.anlp.jp/proceedings/annual_meeting/2007/pdf_dir/PL3-2.pdf),
  not a reproduction of their experiment.
- Two-ply expected own options and mass, worst-case own reply counts, and
  probability of an empty own frequency pool under the assumed reply policy.
- Alternating discounted mass scores at horizons 1, 2, 4 and 8 and at the
  infinite horizon; score percentiles and heuristic regret against every safe
  dictionary alternative available in that position.

For remaining eligible safe words, let `M[i]` be their summed frequency mass
at starting kana `i`. Let `P[i,j]` be the probability of ending at `j` when
sampling a word starting at `i` with weight `frequency ** alpha`. Set
`r[i] = log1p(M[i] / mass_scale)` (default), or use linear mass. Then:

```text
Q = -r + gamma P r - gamma² P² r + ...
  = -(I + gamma P)^(-1) r,     0 <= gamma < 1
```

Evaluate a move at its ending kana: higher is preferable to the player who
just moved. The first negative term penalizes the opponent's options; the
next positive term rewards one's own expected options. The default mass scale
is one occurrence per million. This scale and the log transformation are
modeling choices, not mathematically privileged definitions of word quality.

Already-used words and the proposed word are removed exactly. The infinite
lookahead then **freezes the graph**: it does not remove words used in future
turns. The separate two-ply calculation also removes the opponent's reply.
Fast per-candidate matrix updates are tested against full recomputation.

Important limitations: this is fixed-policy evaluation, not minimax or a win
probability. Corpus frequency is not calibrated human recall. Uncovered words
are not necessarily rare. Empty frequency pools terminate the modeled walk
without an extra terminal reward; they can still have legal dictionary words.
Such destinations are flagged and excluded from headline kana rankings, but
remain in all-dictionary alternative comparisons, so their apparent advantage
can be a coverage artifact. `ん`-trap shares describe possible mistakes, not
failure probabilities: the safe transition policy never chooses those words.
Illegal moves have no strategic score, and infrastructure-failure matches are
marked noncompetitive. Do not aggregate this into a model leaderboard yet.

### Diagnosing what lookahead contributes

```sh
python3 scripts/diagnose_scores.py
python3 scripts/diagnose_scores.py --gammas 0 0.5 0.85 0.99 --skip-matches
```

This offline diagnostic writes a fresh `results/score-diagnostics/` folder with
`summary.txt`, `analysis.json`, and `moves.jsonl`. It does not modify games,
the vocabulary, frequency data, model prompts or leaderboard scores.

It decomposes both log- and linear-mass scores through 128 reward terms.
For each depth it reports variation across initially frequency-supported kana,
adjacent-turn cancellation of both the mean and the variation, correlation of
finite versus infinite rankings, and absolute versus centered tail error.
Centered error removes shared offsets: rankings can converge long before
absolute scores, especially at discount 0.99. Pair ratios near zero indicate
cancellation; ratios with near-zero denominators are numerically uninformative.

Separately it propagates starting-kana distributions and measures their maximum
and average pairwise total-variation distance. Empty transitions lead to an
absorbing cemetery state rather than renormalizing surviving walks. Survival
probability is reported so common termination is not mistaken for mixing.
These are frozen-graph diagnostics, not measurements of actual game trajectories.

Coverage checks partition excluded safe readings into absent measurements,
ambiguity-policy exclusions, and below-threshold/zero readings. Sensitivity
comparisons include alternative measured thresholds, lower-bound ambiguity
handling, and square-root frequency weighting. Rankings are compared on a
fixed set of baseline-supported kana. Artificial scenarios assign every
baseline-excluded word 0.001, 0.01, 0.1 or 1 occurrence per million, or give all
dictionary words equal weight. These are deliberately synthetic stress tests,
not frequency estimates, empirical bounds, or a recommended baseline policy.

Saved-game audits compare the same move scores under three alternative pools:
all safe dictionary words; words whose destinations have measured replies (or
are genuine dictionary dead ends); and measured words with those destinations.
The graph is unchanged by this filtering. A chosen word outside a restricted
pool has no conditional percentile, not a score of zero. Only valid turns in
matches without infrastructure failures are included. Filtering does not cure
incomplete frequency coverage, and these percentiles are not validated skill
scores.

### Word frequency in text transcripts

For per-kana vocabulary and frequency exploration, run:

```sh
python3 scripts/analyze_kana.py
python3 scripts/analyze_kana.py --thresholds 0 0.01 0.1 1 10 --alpha 0.5
python3 scripts/analyze_kana.py --frequency-policy lower
```

Each run creates a new `results/analysis/` folder with a readable `summary.txt`,
`analysis.json`, and `word-distributions.jsonl`. The default excludes readings
with any ambiguous frequency contribution; `lower` includes only their
uniquely assigned lower counts. Neither mode sums ambiguous upper counts.
Thresholds use occurrences per million full corpus tokens. `alpha` controls
conditional sampling weights, `frequency ** alpha`; default 1 means direct
frequency weighting. This analyzes initial positions, with no used words.

Per-kana results include dictionary counts, safe counts, JMdict common counts,
frequency coverage, threshold retention, aggregate corpus-frequency mass,
top-k probability shares, entropy and effective candidate counts, and how many
words account for 50/90/95/99% of sampling probability. `analysis.json` includes
frequency ECDF points and probability-weighted CDFs at fixed cutoffs, plus
next-kana transition probabilities and expected baseline reply counts. The
per-word file contains the complete descending probability/CDF sequence at
threshold 0, not just the examples printed in the text report. Empty pools
have no conditional distribution. A word ending in `ん` is counted separately
and excluded from safe pools. The 72 standard full-size kana (including `ん`
and `ゔ`) and any extra initials observed in the database are all reported.

"Corpus token mass" means matched frequency per million divided by one million.
"Baseline vocabulary share" means the kana's fraction of frequency mass within
the covered safe vocabulary; it does not predict how often play reaches that
kana. The transition matrix is a static starting-position diagnostic, not a
long-game simulation. Source hashes are saved, and a frequency index from a
different referee vocabulary is rejected. No APIs, paid calls or packages
are required.

The working default is now **TUBELEX Japanese**, a YouTube-subtitle frequency
resource described in [Nohejl et al., COLING 2025](https://aclanthology.org/2025.coling-main.641/).
The downloaded source is pinned to repository revision
`7cb5fb36add76b83a266d1967536e1a1d3faa513`, with its BSD-3-Clause license
retained at `data/raw/TUBELEX-LICENSE.txt`. Reproduce the active index with:

```sh
python3 scripts/build_tubelex_frequency.py --download
python3 scripts/show_games.py
```

This builds `data/processed/word-frequency.json`, which the pilot and transcript
viewer load automatically. Existing saved transcripts can be regenerated by
passing their run directory to `show_games.py`. No model calls are needed.

TUBELEX's lemma list has word counts and a majority POS label but no readings.
The importer selects ordinary-noun majority labels and matches written forms
through eligible senses in the full pinned JMdict XML, honoring reading/form
restrictions. UniDic origin suffixes such as `マップ-map` are removed when
the Japanese prefix matches a dictionary form. It sums contributions from forms that unambiguously map to one
reading. If a form has multiple eligible noun readings, the transcript shows
a lower–upper range: the lower estimate excludes that form's count, and the
upper includes it. It never assigns an ambiguous form's full count as certain
frequency for every reading. These are bounds on matched-form contributions,
not confidence intervals or exact noun-pronunciation frequencies. Source
majority-POS counts may include other parts of speech and dictionary coverage
cannot resolve every pronunciation. Exact spelling matching also misses some
lemmas and multiword compounds.

Per-million rates use the source's full `[TOTAL]` token count, not our selected
noun subset. Ranks are competition ranks over positive uniquely assigned
counts within matched benchmark readings, and are shown only for estimates
without ambiguous contributions. Missing matches remain unavailable. The
index records source hashes, join policy, ambiguity statistics and coverage.
The source is subtitle language; familiarity and human retrieval remain
proxies, not validated properties of our baseline.

The BCCWJ importer below is retained as an optional alternative. Its official
repository returned HTTP 503 when we attempted installation. Running either
importer replaces the active annotation index, not the referee vocabulary.

`scripts/build_frequency.py --download` downloads the official NINJAL BCCWJ1
short-unit (SUW) and long-unit (LUW) frequency archives and builds a separate
`data/processed/word-frequency.json` index. It does not alter the frozen
referee database or change legality. To import only one available list, use
`--units suw` or `--units luw`. Existing archives in `data/raw/` are reused.

```sh
python3 scripts/build_frequency.py --download
python3 scripts/show_games.py
```

`games.txt` includes each played word's occurrences per million corpus tokens
and noun-reading rank. SUW and LUW have different tokenizations and denominators;
their frequencies are reported separately, never added together. Rank is
recomputed over aggregated eligible noun readings within each source, not the
source's original all-parts-of-speech rank and not just our vocabulary subset.
Ties share a rank. Noun homophones are summed; proper nouns, numeral nouns,
and non-noun rows are excluded. Counts are matched by normalized lemma reading,
not by JMdict sense, and therefore are a reading-frequency proxy. Corpus noun
classification and JMdict eligibility are not identical. No frequency-based
legality filter or strategic score is applied.

Matching is exact after NFKC and katakana-to-hiragana conversion: long vowels
are not guessed, compounds are not reconstructed from component frequencies,
and missing matches show `unavailable`, never zero. Corpus age, writing-domain
bias, tokenization and morphological analysis errors limit its use as a proxy
for familiarity or model knowledge. The index records archive SHA-256 values,
source links, filtering policy and vocabulary coverage. New pilot manifests
record the annotation index hash when installed; raw match logs stay unchanged.

NINJAL provides the lists for research/educational use. See the
[source page](https://clrd.ninjal.ac.jp/bccwj/en/freq-list.html) and
[manual](https://clrd.ninjal.ac.jp/bccwj/data-files/frequency-list/BCCWJ_frequencylist_manual_ver1_0.pdf)
for conditions before redistributing corpus data. Downloaded archives are
ignored by Git; the generated index is not automatically granted a permissive
license by this project.

### Direct DeepSeek pilot

The pilot uses the direct DeepSeek API and your DeepSeek credits. Its initial
comparison is `deepseek-flash` with thinking disabled versus the same model
with thinking enabled at `low` effort. These are two modes of one model, not
two independent model families. Current API documentation:
https://api-docs.deepseek.com/api/create-chat-completion/

Set `DEEPSEEK_API_KEY` in your local shell or secret manager; do not commit it
or paste it into chat. From the repository directory:

```sh
python3 scripts/run_pilot.py --dry-run
python3 scripts/run_pilot.py
python3 scripts/run_pilot.py --limit 10
```

The default runs just two games from `か`, swapping seats. The full pilot runs
ten games across five provisional openings with both player orders. Each game
has a 60-turn cap. Each mode has the same 4,096-token completion cap; for
thinking mode that includes reasoning and the final answer. The API ignores
temperature in thinking mode, so this comparison is not guaranteed deterministic.
The two-game smoke run permits at most 120 model turns; the ten-game pilot permits
at most 600. With two retries enabled, these bounds become 360 and 1,800 HTTP
attempts respectively. The dry run prints the actual bound for the selected
configuration, excluding bot turns. Turn caps are recorded as capped games,
not evidence that the players have equal ability.

### Automatic API retries

DeepSeek and OpenRouter retry a failed request up to twice (three attempts
total), with 2-second then 4-second backoff. Eligible failures are connection
resets/disconnects, timeouts, incomplete response reads, temporary DNS lookup
failures, and HTTP 408/429/500/502/503/504. A valid `Retry-After` header can
increase the delay; if it requests more than 60 seconds, the run stops rather
than retrying early. Set `"max_retries": 0` on an LLM player to disable retries
(accepted values: 0, 1, or 2).

Only the same pending HTTP request is retried. Completed moves are not replayed,
and the bot is not asked for another move while the request is pending. Invalid
words, truncated generations, malformed JSON, authentication failures, and
certificate/TLS errors are not retried. Exhaustion stops the pilot as an
infrastructure error with no competitive winner.

Successful turns include `metadata.transport` with attempt counts, sanitized
failure types/statuses, delays, and total transport latency. Exhausted requests
are recorded in the match's `error_metadata`; summary token counts cover only
received responses. A provider may have processed and billed a disconnected
request, so retrying can incur an additional charge. No idempotency or exact
cost guarantee is assumed. This is in-process retry, not restart/resume: a
previously stopped run is not automatically continued from its journal.

Change `config/pilot-deepseek.json` to insert other models, modes, or players.
Each player has a unique experiment `id`, a `label`, `provider`, `model`, and
generation settings. Providers currently supported are `deepseek`, `openrouter`,
and `bot`; bot models are `greedy` and `search`. OpenRouter entries use
`OPENROUTER_API_KEY`. Adding another native provider means implementing the
small `CompletionClient` interface and registering it in `factory.py`.

Every execution writes a new directory under `results/pilots/` containing:

- `manifest.json`: player settings, schedule, exact prompt, and vocabulary hash.
- `turns.jsonl`: flushed per-turn journal including request prompt, response,
  reasoning when returned, usage, fingerprint, and latency.
- `matches.jsonl`: complete matches with referee outcomes.
- `summary.json`: wins, ending reasons, and token totals.

Reasoning is retained for audit but never submitted as a move or passed back
to either player. Each turn is a fresh request containing the required kana
and the complete sorted set of used words. The pilot tests recall of this
explicit state, rather than chronological conversation memory. No dictionary
entries or tools are provided to the models.

Infrastructure errors and truncated outputs stop the pilot and are excluded
from competitive rankings. Actual invalid model moves still lose normally.
DeepSeek does not provide OpenRouter's `usage.cost`, so token totals are the
cost evidence here; the existing website exporter does not calculate direct
DeepSeek dollar charges. Do not interpret its zero cost as free inference.

The pilot and offline tests have been added code-first. No environment,
dependency installation, test execution, or paid API execution was performed
when adding them.

`scripts/run_match.py` accepts `greedy`, `search`, or a configured
`model:<OpenRouter ID>` for each seat. It appends the complete match record to
`results/raw/matches.jsonl`. Model players require `OPENROUTER_API_KEY`.

`scripts/export_results.py` converts those append-only records into
`web/data/results.json`. The exporter calculates win rate, valid-move rate,
cost per match, and a chronological Elo rating. Official runs should use a
fresh results file and a precommitted schedule because Elo depends on order.

`scripts/make_schedule.py` creates that deterministic, balanced schedule from
the enabled model roster and experiment configuration without making API
calls.

No model aliases should be silently advanced during an official leaderboard period. Before a run, resolve every configured model to its canonical slug and record that value with the result.

## Environment variables

### Offline memory-baseline sensitivity test

Run `python3 scripts/test_memory_baseline.py` (no API calls). The default
576-game experiment uses eight openings, three seed pairs, both seat orders,
and weak/current/strong recognition settings. It compares MemoryBot self-play
against perfect-memory frequency sampling, minimum-reply-mass pressure, and
two-ply pressure (discount 0.85). Each game has a 2,000-move safety cap.

Results go to `results/memory-validation/<UTC timestamp>/`: full matches,
observations, summary, and a manifest with settings, schedule, dictionary and
source hashes. A stratified third of matches is replayed exactly. Seat-swaps
share seeds, so do not treat all games as independent samples. These are
mechanism probes, not human-calibrated players or estimated win probabilities.
See `results/memory-validation/20261028T053101Z/findings.md` for the initial run.

The code expects `OPENROUTER_API_KEY` at runtime. No secrets belong in this repository.

## Status

The current vocabulary filter is `noun-v3`. It accepts an eligible standalone
noun sense even when that same sense also supports suffix usage (for example,
まくら / 枕 / pillow). Suffix-only senses and all other exclusion rules remain
unchanged. Both SQLite dictionaries, English glosses, and TUBELEX mappings
have been regenerated from the existing pinned source files. The prior
`noun-v2` derived data and hashes are retained in
`data/processed/archive/noun-v2-before-mixed-suffix-fix/`; historical games and
public website snapshots are not rescored or relabeled by this change.
Future runs use the new vocabulary version and hashes, so baseline pools may
differ from earlier runs. Comparisons across versions must report this change.

This is an initial architecture and website skeleton. The match scheduler,
statistical analysis, and complete JMdict POS policy remain to be implemented.

