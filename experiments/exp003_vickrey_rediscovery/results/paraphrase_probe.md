# exp003 — paraphrased-seed retrieval probe

Direct Chroma queries (bypassing `hypothesize`) on four phrasings of the same Vickrey-rediscovery claim. Top-15 merged neighbors per seed. Question: under any phrasing, does a Camerer BGT chunk reach the top-10?

## Seed A_original

**Phrasing:** Tier-2 experimental vocabulary (verbatim from iter-028)

> In repeated single-round sealed-bid second-price auctions with four LLM bidders drawing independent private valuations from U[0, 100] and no priming on auction theory, bidders converge on submitting bids approximately equal to their private valuations (observed truthful-bid fraction: 100.00% of trials had mean |bid − valuation| ≤ 5).

| rank | doc_id | score | source | book | title |
|---|---|---|---|---|---|
| 1 | `2605.22438` | 0.6450 | live_arxiv | `arxiv` | Do Not Trust The Auctioneer: Learning to Bid in Feedback-... |
| 2 | `osborne_rubinstein-chunk-187` | 0.6406 | foundational | `osborne_rubinstein` | 2 Nash Equilibrium |
| 3 | `2605.21934` | 0.6218 | live_arxiv | `arxiv` | Single-Item Auctions with a Monopolist Intermediary |
| 4 | `osborne_rubinstein-chunk-127` | 0.6082 | foundational | `osborne_rubinstein` | 2 Nash Equilibrium |
| 5 | `2605.22667` | 0.6029 | live_arxiv | `arxiv` | Imperfect Commitment in Maximal Extractable Value Auctions |
| 6 | `osborne_rubinstein-chunk-125` | 0.5932 | foundational | `osborne_rubinstein` | 2 Nash Equilibrium |
| 7 | `evolutionary-game-theory_compress-chunk-1012` | 0.5824 | foundational | `evolutionary-game-theory_compress` | (none) |
| 8 | `osborne_rubinstein-chunk-1632` | 0.5803 | foundational | `osborne_rubinstein` | 13 The Core |
| 9 | `osborne_rubinstein-chunk-1862` | 0.5773 | foundational | `osborne_rubinstein` | 14 Stable Sets, the Bargaining Set, and the Shapley Value |
| 10 | `osborne_rubinstein-chunk-738` | 0.5746 | foundational | `osborne_rubinstein` | 7 Bargaining Games |
| 11 | `osborne_rubinstein-chunk-2123` | 0.5731 | foundational | `osborne_rubinstein` | 15 The Nash Solution |
| 12 | `hofbauer_sigmund_egpd-chunk-90` | 0.5721 | foundational | `hofbauer_sigmund_egpd` | (none) |
| 13 | `osborne_rubinstein-chunk-2103` | 0.5647 | foundational | `osborne_rubinstein` | 15 The Nash Solution |
| 14 | `osborne_rubinstein-chunk-865` | 0.5647 | foundational | `osborne_rubinstein` | 8 Repeated Games |
| 15 | `2605.17607` | 0.5621 | live_arxiv | `arxiv` | Convergence of Stochastic First-Order Algorithms in Bertr... |

## Seed B_camerer_behavioral

**Phrasing:** Behavioral-economics / Camerer vocabulary

> In behavioral economics experiments with second-price sealed-bid auctions, subjects systematically converge on truthful value-revelation as the dominant strategy, an empirical finding that holds across diverse experimental populations and is replicated here with four LLM agents.

| rank | doc_id | score | source | book | title |
|---|---|---|---|---|---|
| 1 | `2605.17698` | 0.6174 | live_arxiv | `arxiv` | Agent Bazaar: Enabling Economic Alignment in Multi-Agent ... |
| 2 | `2605.19915` | 0.6124 | live_arxiv | `arxiv` | LLM Agents Make Collective Belief Dynamics Programmable: ... |
| 3 | `2605.17662` | 0.6113 | live_arxiv | `arxiv` | Learning Through Imitation: An Experiment |
| 4 | `osborne_rubinstein-chunk-1710` | 0.6113 | foundational | `osborne_rubinstein` | 13 The Core |
| 5 | `camerer_bgt-chunk-71` | 0.6072 | foundational | `camerer_bgt` | (OCR full document) |
| 6 | `2605.22095` | 0.6069 | live_arxiv | `arxiv` | Not Yet: Humans Outperform LLMs in a Colonel Blotto Tourn... |
| 7 | `2605.17607` | 0.6049 | live_arxiv | `arxiv` | Convergence of Stochastic First-Order Algorithms in Bertr... |
| 8 | `hofbauer_sigmund_egpd-chunk-44` | 0.6042 | foundational | `hofbauer_sigmund_egpd` | (none) |
| 9 | `evolutionary-game-theory_compress-chunk-836` | 0.6005 | foundational | `evolutionary-game-theory_compress` | (none) |
| 10 | `2605.23099` | 0.5943 | live_arxiv | `arxiv` | SVR-MAD: A Bayesian-Inspired Framework for Posterior-Guid... |
| 11 | `learning_mutations_and_long.pdf-chunk-65` | 0.5933 | foundational | `learning_mutations_and_long.pdf` | (none) |
| 12 | `evolutionary-game-theory_compress-chunk-711` | 0.5888 | foundational | `evolutionary-game-theory_compress` | (none) |
| 13 | `2605.21117` | 0.5883 | live_arxiv | `arxiv` | When Do Markets Work? Multiplex Networks and Efficiency |
| 14 | `2605.22438` | 0.5873 | live_arxiv | `arxiv` | Do Not Trust The Auctioneer: Learning to Bid in Feedback-... |
| 15 | `2605.15472` | 0.5862 | live_arxiv | `arxiv` | Estimated Dynamic Equilibrium Model: Supply and Demand as... |

## Seed C_myerson_mechanism_design

**Phrasing:** Mechanism-design / Myerson vocabulary

> Vickrey's incentive-compatibility result for the second-price sealed-bid mechanism states that bidding one's private valuation is a weakly dominant strategy; empirical play in a four-bidder setting with independent valuations on a bounded interval confirms this rediscovery.

| rank | doc_id | score | source | book | title |
|---|---|---|---|---|---|
| 1 | `osborne_rubinstein-chunk-127` | 0.6833 | foundational | `osborne_rubinstein` | 2 Nash Equilibrium |
| 2 | `osborne_rubinstein-chunk-187` | 0.6493 | foundational | `osborne_rubinstein` | 2 Nash Equilibrium |
| 3 | `2605.26639` | 0.6355 | live_arxiv | `arxiv` | Suppression and Empowerment in Contests |
| 4 | `evolutionary-game-theory_compress-chunk-250` | 0.6352 | foundational | `evolutionary-game-theory_compress` | (none) |
| 5 | `evolutionary-game-theory_compress-chunk-1087` | 0.6263 | foundational | `evolutionary-game-theory_compress` | (none) |
| 6 | `osborne_rubinstein-chunk-416` | 0.6259 | foundational | `osborne_rubinstein` | 4 Rationalizability and Iterated Elimination of Dominated... |
| 7 | `osborne_rubinstein-chunk-414` | 0.6225 | foundational | `osborne_rubinstein` | 4 Rationalizability and Iterated Elimination of Dominated... |
| 8 | `evolutionary-game-theory_compress-chunk-484` | 0.6087 | foundational | `evolutionary-game-theory_compress` | (none) |
| 9 | `evolutionary-game-theory_compress-chunk-637` | 0.6066 | foundational | `evolutionary-game-theory_compress` | (none) |
| 10 | `2605.17607` | 0.5962 | live_arxiv | `arxiv` | Convergence of Stochastic First-Order Algorithms in Bertr... |
| 11 | `2605.22438` | 0.5926 | live_arxiv | `arxiv` | Do Not Trust The Auctioneer: Learning to Bid in Feedback-... |
| 12 | `osborne_rubinstein-chunk-2097` | 0.5915 | foundational | `osborne_rubinstein` | 15 The Nash Solution |
| 13 | `evolutionary-game-theory_compress-chunk-207` | 0.5891 | foundational | `evolutionary-game-theory_compress` | (none) |
| 14 | `osborne_rubinstein-chunk-2129` | 0.5884 | foundational | `osborne_rubinstein` | 15 The Nash Solution |
| 15 | `osborne_rubinstein-chunk-1710` | 0.5878 | foundational | `osborne_rubinstein` | 13 The Core |

## Seed D_textbook_minimal

**Phrasing:** Textbook minimal phrasing

> In a second-price (Vickrey) auction with N=4 bidders drawing independent private valuations, every bidder's weakly dominant action is to bid their valuation. Empirical bidding behavior in LLM-driven plays matches this prediction.

| rank | doc_id | score | source | book | title |
|---|---|---|---|---|---|
| 1 | `osborne_rubinstein-chunk-127` | 0.7534 | foundational | `osborne_rubinstein` | 2 Nash Equilibrium |
| 2 | `osborne_rubinstein-chunk-187` | 0.6672 | foundational | `osborne_rubinstein` | 2 Nash Equilibrium |
| 3 | `osborne_rubinstein-chunk-126` | 0.6384 | foundational | `osborne_rubinstein` | 2 Nash Equilibrium |
| 4 | `osborne_rubinstein-chunk-420` | 0.6279 | foundational | `osborne_rubinstein` | 4 Rationalizability and Iterated Elimination of Dominated... |
| 5 | `osborne_rubinstein-chunk-125` | 0.6251 | foundational | `osborne_rubinstein` | 2 Nash Equilibrium |
| 6 | `osborne_rubinstein-chunk-1632` | 0.6169 | foundational | `osborne_rubinstein` | 13 The Core |
| 7 | `2605.21934` | 0.6133 | live_arxiv | `arxiv` | Single-Item Auctions with a Monopolist Intermediary |
| 8 | `osborne_rubinstein-chunk-1862` | 0.6114 | foundational | `osborne_rubinstein` | 14 Stable Sets, the Bargaining Set, and the Shapley Value |
| 9 | `osborne_rubinstein-chunk-414` | 0.6106 | foundational | `osborne_rubinstein` | 4 Rationalizability and Iterated Elimination of Dominated... |
| 10 | `osborne_rubinstein-chunk-416` | 0.6087 | foundational | `osborne_rubinstein` | 4 Rationalizability and Iterated Elimination of Dominated... |
| 11 | `2605.22438` | 0.6022 | live_arxiv | `arxiv` | Do Not Trust The Auctioneer: Learning to Bid in Feedback-... |
| 12 | `evolutionary-game-theory_compress-chunk-484` | 0.6011 | foundational | `evolutionary-game-theory_compress` | (none) |
| 13 | `osborne_rubinstein-chunk-419` | 0.5997 | foundational | `osborne_rubinstein` | 4 Rationalizability and Iterated Elimination of Dominated... |
| 14 | `evolutionary-game-theory_compress-chunk-967` | 0.5994 | foundational | `evolutionary-game-theory_compress` | (none) |
| 15 | `learning_mutations_and_long.pdf-chunk-21` | 0.5977 | foundational | `learning_mutations_and_long.pdf` | (none) |

## Cross-seed summary: foundational-book appearances in top-10

| book | seeds (1-indexed) with appearance | count |
|---|---|---|
| `camerer_bgt` | [2] | 1 |
| `evolutionary-game-theory_compress` | [1, 2, 3] | 3 |
| `hofbauer_sigmund_egpd` | [2] | 1 |
| `osborne_rubinstein` | [1, 2, 3, 4] | 4 |

**Camerer BGT reached top-10 under seeds [2] — the original-seed retrieval gap is at least partially phrasing-dependent.**
