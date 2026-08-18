# Research Grounding for the Multi-Agent Restaurant Review Analysis System
### COS30018 Intelligent Systems — literature backing for design choices

**Verification note.** Every reference in Section 3 was checked with a live web search/fetch during
this pass (July 2026). "Verified" means the arXiv ID / DOI, author list, title and year returned by
the search match what is cited here. Where a *venue* (e.g. "ACL 2024") was reported by search results
but not independently confirmed on the publisher page, it is flagged. Nothing here is cited from memory
alone.

---

## 1. MAPPING TABLE — design choice → supporting papers → one-sentence justification

| # | Design choice in the system | Supporting refs | How the paper(s) support it |
|---|---|---|---|
| A | **4 specialized LLM agents** (Analysis / Reasoning / Strategy / Report), each with a narrow role | [1] AutoGen, [2] MetaGPT, [3] CAMEL, [4] ChatDev, [5] Guo survey | These works show that decomposing a task across role-specialized, conversing LLM agents outperforms a single monolithic agent and is a recognized paradigm. |
| B | **LangGraph "simple-hub" supervisor** routing between agents (critical vs non-critical, retry/skip/halt) | [1] AutoGen (GroupChat *manager*), [2] MetaGPT (SOP-driven assembly line), [5] Guo survey | A central coordinator that assigns/sequences agent turns is exactly the "manager/orchestrator" role these frameworks describe; the *specific* retry/skip/halt policy is the team's own (see Gaps). |
| C | **Structured JSON output validated against Pydantic + self-correction re-prompt (max 2 retries) → AgentError** | [6] Self-Refine, [7] Reflexion, [8] CRITIC, [9] Pan self-correction survey | All four establish that feeding an LLM back its own error signal and re-prompting improves output; validation-error-as-feedback is a post-hoc, external-feedback self-correction instance. |
| D | **Aspect-based sentiment over 7 categories with per-aspect polarity, via LLM prompting (no fine-tuned classifier)** | [14] SemEval-2014 Task 4, [15] Simmering & Huoviala, [16] Wu et al. multilingual ABSA, [17] Niimi restaurant LLM | [14] defines the ABSA task on restaurant reviews; [15][16][17] evaluate LLMs doing ABSA by prompting and quantify the accuracy/cost trade-off vs fine-tuned models. |
| E | **Reasoning Agent: cross-review pattern detection + root-cause inference** | [18] Chain-of-Thought, [19] ReAct, [20] Malik & Bilal review-NLP survey | [18][19] justify eliciting explicit intermediate reasoning steps for inference tasks; [20] frames mining/aggregating reviews for actionable business insight. |
| F | **Tier-3 evaluation = LLM-as-judge with written rubrics + independent judge model** | [10] Zheng MT-Bench, [11] Liu G-Eval; biases: [12] Wang, [13] Panickssery | [10][11] validate rubric/CoT LLM grading against human judgement; [12][13] document the position-bias and self-preference biases you must list under Threats to Validity. |
| G | **Tier-2 gold set (73 reviews) scored with accuracy + macro-F1** | [21] Sokolova & Lapalme | [21] is the standard methodological reference showing macro-averaged F1 weights all classes equally, which is the right choice for imbalanced sentiment/aspect classes. |
| H | **Data = Yelp Open Dataset restaurant reviews** | [22] Zhang, Zhao & LeCun; [14] SemEval restaurant domain; [17] Niimi | [22] is the canonical work that turned Yelp reviews into a widely-used text-classification benchmark; [14][17] confirm restaurant reviews as an established ABSA/eval domain. |
| I | **Provider layer: cloud (Gemini) + local (Ollama) behind one OpenAI-compatible abstraction; run provenance** | [17] Niimi (local mid-size LLM + majority voting) | [17] is the closest published motivation — mid-size *local* LLMs can be competitive/robust for restaurant-review sentiment; the abstraction layer itself is engineering (see Gaps). |

---

## 2. PER-CHOICE NOTES (what each paper actually claims + honest weak-support flags)

### Area 1 — Multi-agent LLM systems & role specialization  → choices A, B
- **[1] AutoGen (Wu et al., 2023).** Open-source framework for building apps from multiple *conversable, customizable* agents; agents combine LLMs, tools and human input, and a `GroupChatManager` can coordinate turn-taking. Directly supports both "multiple specialized agents" (A) and "a central coordinator" (B). Empirical demos span math, coding, QA, decision-making.
- **[2] MetaGPT (Hong et al., 2023; ICLR 2024).** Encodes human Standard Operating Procedures (SOPs) into prompts and uses an **assembly-line** paradigm to assign distinct roles (e.g. PM, architect, engineer). Strongest support for *role specialization with a defined pipeline order* — very close to your Analysis→Reasoning→Strategy→Report chain.
- **[3] CAMEL (Li et al., 2023; NeurIPS 2023).** Role-playing framework where agents cooperate autonomously via "inception prompting." Supports the general claim that assigning explicit roles produces useful cooperative behaviour.
- **[4] ChatDev (Qian et al., 2023; ACL 2024).** Specialized LLM agents run a chat-chain across design/coding/testing phases; shows role-partitioned agents complete a real multi-stage workflow. Good analogy for a staged review-analysis pipeline.
- **[5] Guo et al. survey (2024).** Survey of LLM-based multi-agent systems: profiling, communication, coordination. Use as the umbrella citation that role-specialized multi-agent LLM design is an established research area.
- **Honest note (choice B):** No cited paper names a "simple-hub" or a critical/non-critical **retry/skip/halt** policy. The *idea* of a manager/orchestrator is well supported ([1][2][5]); the specific recovery policy and criticality tags are the team's own design (→ Gaps). The LangGraph "supervisor" pattern itself is framework documentation, not peer-reviewed literature.

### Area 2 — Self-correction from validation feedback  → choice C
- **[6] Self-Refine (Madaan et al., 2023; NeurIPS 2023).** Same LLM generates → critiques → refines its own output iteratively, no extra training; ~20% average gain across 7 tasks. Motivates the refine-on-feedback loop.
- **[7] Reflexion (Shinn et al., 2023; NeurIPS 2023).** Converts environment feedback (incl. binary success/failure) into *verbal* feedback stored in memory to improve the next attempt. Your Pydantic `ValidationError` string is exactly this kind of external feedback signal fed back into the prompt.
- **[8] CRITIC (Gou et al., 2023; ICLR 2024).** LLM verifies its output using an *external tool*, then corrects; "Verify ⇒ Correct ⇒ Verify" loop. A schema validator is the external verifier in your instantiation — the tightest analogue to "validate, then re-prompt with the error."
- **[9] Pan et al. survey (2023; TACL 2024).** Taxonomizes self-correction into training-time / generation-time / **post-hoc** correction with automated feedback. Your validate-and-retry sits squarely in "post-hoc correction with automated (non-human) feedback."
- **Honest note:** These papers validate *self-correction from feedback* in general. None specifically studies "Pydantic/JSON-schema validation error as the feedback channel" or the exact `max_retries = 2` cutoff — that number is an engineering choice, not a literature-derived optimum.

### Area 3 — Aspect-based sentiment analysis by LLM prompting  → choice D
- **[14] Pontiki et al., SemEval-2014 Task 4.** The foundational shared task that *defines* ABSA (identify aspects of a target entity + sentiment per aspect) and ships the **restaurant** and laptop benchmark datasets. This is the correct primary citation for "aspect-based" and for the restaurant domain. Note: its aspect categories differ from your 7 custom categories (yours are a project-defined taxonomy).
- **[15] Simmering & Huoviala (2023), "LLMs for ABSA."** Evaluates GPT-3.5/GPT-4 on ABSA; fine-tuned GPT-3.5 reaches SOTA F1 = 83.8 on SemEval-2014 joint aspect+polarity, but at ~1000× the parameters/inference cost of small specialized models; detailed prompts help zero/few-shot but not fine-tuned. Supports "LLM prompting can do ABSA" **and** honestly frames the cost trade-off.
- **[16] Wu et al. (2024/2025), zero-shot multilingual ABSA with LLMs.** Concludes LLMs are promising but **generally fall short of fine-tuned task-specific models**, and simpler zero-shot prompts often beat elaborate strategies (esp. English). Important balancing citation — cite it so the report does not overclaim prompting-based ABSA.
- **[17] Niimi (2024), restaurant sentiment with local LLMs + majority voting.** Mid-size *local* LLM with majority voting over multiple inferences is more robust than a single large-model pass; also analyzes how each aspect affects the overall rating. Supports both aspect-level restaurant analysis (D) and the local-provider option (I).
- **Honest note:** The literature supports LLM-prompted ABSA as *feasible* but repeatedly finds it below fine-tuned baselines. The report should present the prompting choice as a pragmatic/flexibility decision, not an accuracy-optimal one.

### Area 4 — Reasoning / root-cause inference from reviews  → choice E
- **[18] Wei et al., Chain-of-Thought (NeurIPS 2022).** Intermediate reasoning steps markedly improve LLM performance on reasoning tasks. Grounds asking the Reasoning Agent to reason explicitly before emitting patterns/root-causes.
- **[19] Yao et al., ReAct (ICLR 2023).** Interleaving reasoning traces with actions improves accuracy and interpretability; widely regarded as a foundation of agentic LLM design. Supports a reasoning-then-conclude agent whose traces are inspectable.
- **[20] Malik & Bilal (2024), PeerJ CS survey.** Surveys 154 papers (2013–2023) on NLP over online customer reviews; taxonomy includes review analysis and customer-feedback/satisfaction, i.e. turning reviews into business insight. Frames the *purpose* of the Reasoning/Strategy stages.
- **Honest note (weak/indirect support):** There is **no cited paper** that validates "LLM infers the *root cause* of restaurant complaints from a set of reviews" as a benchmarked task. CoT/ReAct justify the *reasoning mechanism*; the survey justifies the *goal*; but root-cause *plausibility* remains unvalidated by external ground truth — which is precisely why Tier-3 uses an LLM judge with a rubric. Flag this as a novelty/validity point.

### Area 5 — LLM-as-judge evaluation (Tier 3) + its biases  → choice F
- **[10] Zheng et al., MT-Bench / Chatbot Arena (NeurIPS 2023 D&B).** Strong LLM judges (GPT-4) agree with human preference >80% (≈ human–human agreement); *also* explicitly names position, verbosity and self-enhancement biases. Primary citation both **for** LLM-as-judge and **for** its limitations.
- **[11] Liu et al., G-Eval (EMNLP 2023).** LLM + chain-of-thought + form-filling for NLG evaluation; Spearman 0.514 with humans on summarization, beating prior metrics; and warns judges can be biased toward LLM-generated text. Directly supports "rubric-guided LLM scoring of open-ended outputs" (your report-usefulness / recommendation-actionability rubrics).
- **[12] Wang et al., "LLMs are not Fair Evaluators" (2023).** Demonstrates **position bias**: simply swapping candidate order can flip the winner; proposes multiple-evidence + balanced-position calibration. Cite under Threats to Validity and to justify order-swapping / averaging in your judge harness.
- **[13] Panickssery et al., "LLM Evaluators Recognize and Favor Their Own Generations" (2024).** Establishes **self-preference bias** linked to self-recognition — an LLM scores its own outputs higher. This is the concrete reason to use an *independent* judge model, exactly as your design does.
- **Honest note:** These fully support each *component* (rubric grading, independent judge, bias-awareness). No single paper validates your particular three-rubric set (root-cause plausibility / recommendation actionability / report usefulness) — those rubrics are project-authored.

### Area 6 — Evaluation methodology (gold set + macro-F1)  → choice G
- **[21] Sokolova & Lapalme (2009), Information Processing & Management.** Systematic analysis of 24 classification metrics; documents that macro-averaging treats all classes equally while micro-averaging favors large classes — the standard justification for reporting **macro-F1** on imbalanced sentiment/aspect labels.
- **Honest note:** The *three-tier* harness (deterministic checks → human gold set → LLM-judge) is **not a named methodology in the literature.** Each tier is individually well-grounded — schema/deterministic checks are standard software practice; gold-set accuracy/macro-F1 by [21]; LLM-judge by [10][11] — but the **combination into a labelled "three-tier" framework is the team's own construction.** State it that way in the report. Likewise, the 73-review gold-set size and single-vs-multi-annotator protocol are project decisions; no cited paper prescribes them (→ Gaps).

### Area 7 — Yelp Open Dataset usage  → choice H
- **[22] Zhang, Zhao & LeCun (2015), NeurIPS 2015.** Introduced the large-scale text-classification benchmarks (Yelp Review Polarity / Full, Amazon, etc.) that made Yelp reviews a canonical academic corpus for sentiment/rating classification. Best single citation to justify "Yelp reviews are an established research dataset."
- Supporting: [14] uses restaurant reviews for ABSA; [17] studies restaurant-review sentiment with LLMs.
- **Honest note:** The **Yelp Open Dataset** itself has no canonical peer-reviewed "dataset paper" — it is released directly by Yelp for academic use. [22] grounds Yelp-reviews-as-benchmark; cite Yelp's own dataset page for the exact corpus. The SQLite index and 100-reviews-per-restaurant sampling cap are engineering choices with no literature backing (→ Gaps).

---

## 3. VERIFIED REFERENCES (IEEE style)

All entries below were confirmed to exist via web search on this pass. Venue tags marked **(venue not
independently confirmed)** were reported by search results but not verified on the publisher page — the
paper's existence, authors, title, year and arXiv ID are confirmed regardless.

[1] Q. Wu, G. Bansal, J. Zhang, Y. Wu, B. Li, E. Zhu, L. Jiang, X. Zhang, S. Zhang, J. Liu, A. H. Awadallah, R. W. White, D. Burger, and C. Wang, "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation," *arXiv:2308.08155*, 2023. https://arxiv.org/abs/2308.08155

[2] S. Hong, M. Zhuge, J. Chen, X. Zheng, Y. Cheng, C. Zhang, J. Wang, Z. Wang, S. K. S. Yau, Z. Lin, L. Zhou, C. Ran, L. Xiao, C. Wu, and J. Schmidhuber, "MetaGPT: Meta Programming for a Multi-Agent Collaborative Framework," *Int. Conf. on Learning Representations (ICLR)*, 2024; *arXiv:2308.00352*, 2023. https://arxiv.org/abs/2308.00352

[3] G. Li, H. Hammoud, H. Itani, D. Khizbullin, and B. Ghanem, "CAMEL: Communicative Agents for 'Mind' Exploration of Large Language Model Society," *Advances in Neural Information Processing Systems (NeurIPS)*, 2023; *arXiv:2303.17760*. https://arxiv.org/abs/2303.17760

[4] C. Qian, W. Liu, H. Liu, N. Chen, Y. Dang, J. Li, C. Yang, W. Chen, Y. Su, X. Cong, J. Xu, D. Li, Z. Liu, and M. Sun, "ChatDev: Communicative Agents for Software Development," *Proc. 62nd Annual Meeting of the ACL (ACL 2024)*; *arXiv:2307.07924*, 2023. https://arxiv.org/abs/2307.07924

[5] T. Guo, X. Chen, Y. Wang, R. Chang, S. Pei, N. V. Chawla, O. Wiest, and X. Zhang, "Large Language Model based Multi-Agents: A Survey of Progress and Challenges," *arXiv:2402.01680*, 2024. https://arxiv.org/abs/2402.01680

[6] A. Madaan, N. Tandon, P. Gupta, S. Hallinan, L. Gao, S. Wiegreffe, U. Alon, N. Dziri, S. Prabhumoye, Y. Yang, S. Gupta, B. P. Majumder, K. Hermann, S. Welleck, A. Yazdanbakhsh, and P. Clark, "Self-Refine: Iterative Refinement with Self-Feedback," *Advances in Neural Information Processing Systems (NeurIPS)*, 2023; *arXiv:2303.17651*. https://arxiv.org/abs/2303.17651

[7] N. Shinn, F. Cassano, E. Berman, A. Gopinath, K. Narasimhan, and S. Yao, "Reflexion: Language Agents with Verbal Reinforcement Learning," *Advances in Neural Information Processing Systems (NeurIPS)*, 2023; *arXiv:2303.11366*. https://arxiv.org/abs/2303.11366

[8] Z. Gou, Z. Shao, Y. Gong, Y. Shen, Y. Yang, N. Duan, and W. Chen, "CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing," *Int. Conf. on Learning Representations (ICLR)*, 2024; *arXiv:2305.11738*, 2023. https://arxiv.org/abs/2305.11738

[9] L. Pan, M. Saxon, W. Xu, D. Nathani, X. Wang, and W. Y. Wang, "Automatically Correcting Large Language Models: Surveying the Landscape of Diverse Self-Correction Strategies," *Transactions of the ACL (TACL)*, 2024; *arXiv:2308.03188*, 2023. https://arxiv.org/abs/2308.03188

[10] L. Zheng, W.-L. Chiang, Y. Sheng, S. Zhuang, Z. Wu, Y. Zhuang, Z. Lin, Z. Li, D. Li, E. P. Xing, H. Zhang, J. E. Gonzalez, and I. Stoica, "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena," *Advances in Neural Information Processing Systems (NeurIPS), Datasets and Benchmarks Track*, 2023; *arXiv:2306.05685*. https://arxiv.org/abs/2306.05685

[11] Y. Liu, D. Iter, Y. Xu, S. Wang, R. Xu, and C. Zhu, "G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment," *Proc. EMNLP 2023*, pp. 2511–2522; *arXiv:2303.16634*. https://aclanthology.org/2023.emnlp-main.153/

[12] P. Wang, L. Li, L. Chen, Z. Cai, D. Zhu, B. Lin, Y. Cao, Q. Liu, T. Liu, and Z. Sui, "Large Language Models are not Fair Evaluators," *Proc. ACL 2024* (venue not independently confirmed); *arXiv:2305.17926*, 2023. https://arxiv.org/abs/2305.17926

[13] A. Panickssery, S. R. Bowman, and S. Feng, "LLM Evaluators Recognize and Favor Their Own Generations," 2024; *arXiv:2404.13076* (conference venue not independently confirmed). https://arxiv.org/abs/2404.13076

[14] M. Pontiki, D. Galanis, J. Pavlopoulos, H. Papageorgiou, I. Androutsopoulos, and S. Manandhar, "SemEval-2014 Task 4: Aspect Based Sentiment Analysis," *Proc. 8th Int. Workshop on Semantic Evaluation (SemEval 2014)*, Dublin, Ireland, 2014, pp. 27–35. https://aclanthology.org/S14-2004/

[15] P. F. Simmering and P. Huoviala, "Large Language Models for Aspect-Based Sentiment Analysis," *arXiv:2310.18025*, 2023. https://arxiv.org/abs/2310.18025

[16] C. Wu, B. Ma, Z. Zhang, N. Deng, Y. He, and Y. Xue, "Evaluating Zero-Shot Multilingual Aspect-Based Sentiment Analysis with Large Language Models," *arXiv:2412.12564*, 2024/2025. https://arxiv.org/abs/2412.12564

[17] J. Niimi, "Dynamic Sentiment Analysis with Local Large Language Models using Majority Voting: A Study on Factors Affecting Restaurant Evaluation," *arXiv:2407.13069*, 2024. https://arxiv.org/abs/2407.13069

[18] J. Wei, X. Wang, D. Schuurmans, M. Bosma, B. Ichter, F. Xia, E. Chi, Q. Le, and D. Zhou, "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models," *Advances in Neural Information Processing Systems (NeurIPS)*, 2022; *arXiv:2201.11903*. https://arxiv.org/abs/2201.11903

[19] S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan, and Y. Cao, "ReAct: Synergizing Reasoning and Acting in Language Models," *Int. Conf. on Learning Representations (ICLR)*, 2023; *arXiv:2210.03629*, 2022. https://arxiv.org/abs/2210.03629

[20] N. Malik and M. Bilal, "Natural Language Processing for Analyzing Online Customer Reviews: A Survey, Taxonomy, and Open Research Challenges," *PeerJ Computer Science*, vol. 10, e2203, 2024. https://peerj.com/articles/cs-2203/

[21] M. Sokolova and G. Lapalme, "A Systematic Analysis of Performance Measures for Classification Tasks," *Information Processing & Management*, vol. 45, no. 4, pp. 427–437, 2009. https://www.sciencedirect.com/science/article/abs/pii/S0306457309000259

[22] X. Zhang, J. Zhao, and Y. LeCun, "Character-level Convolutional Networks for Text Classification," *Advances in Neural Information Processing Systems (NeurIPS)*, 2015, pp. 649–657; *arXiv:1509.01626*. https://arxiv.org/abs/1509.01626

**Primary data source (not a research paper — cite directly):**
Yelp Inc., "Yelp Open Dataset," https://www.yelp.com/dataset (released for academic use; no canonical peer-reviewed dataset paper — see [22] for the derived benchmark).

---

## 4. GAPS — design choices with no direct literature backing (candidate novelty / to-flag)

These are the parts of the system that the literature does **not** directly validate. They are either
the team's genuine contributions (good — claim them) or engineering choices that should be presented
as such (not as literature-optimal).

1. **"Simple-hub" orchestrator with critical/non-critical agent tagging + retry / skip / halt recovery policy.**
   The manager/orchestrator concept is supported ([1][2][5]) but this *specific* supervision policy —
   deciding per-agent criticality and choosing skip-vs-halt on failure — has no direct citation. This is
   the strongest candidate for a genuine engineering-novelty claim. (LangGraph's "supervisor" is docs,
   not peer-reviewed.)

2. **The named "three-tier evaluation harness" as a single methodology.** Each tier is grounded
   individually (deterministic checks = standard practice; macro-F1 gold set = [21]; LLM-judge = [10][11]),
   but bundling them into a labelled 3-tier framework is the team's own composition. Present it as an
   integration contribution, not a cited method.

3. **Root-cause *plausibility* of the Reasoning Agent.** No benchmark validates LLM root-cause inference
   over restaurant reviews. CoT/ReAct ([18][19]) justify the mechanism; there is no external ground truth,
   which is exactly why you fall back to an LLM-judge rubric — worth stating explicitly as a validity limit.

4. **The 7 custom aspect categories** (food_quality, staff_attitude, pricing, wait_time, ambience,
   cleanliness, other). These are project-defined; SemEval-2014 [14] uses different categories. Not wrong,
   but not a standard taxonomy — say so.

5. **Concrete magic numbers:** `max_retries = 2`, the **73-review** gold-set size, the **100-reviews-per-restaurant**
   sampling cap. All are pragmatic project choices with no literature-derived justification. Do not imply otherwise.

6. **OpenAI-compatible provider abstraction + per-run `run_config` provenance.** Pure software-engineering
   / reproducibility practice. [17] gives partial motivation for *using* local LLMs, but the abstraction
   layer and provenance logging are not literature-backed design claims — present them as good MLOps hygiene.

7. **Pydantic-schema-error as the exact self-correction feedback channel.** The general principle (external
   validator → verbal feedback → re-prompt) is well supported ([7][8][9]); the specific instantiation with
   Pydantic v2 validation strings is your engineering realization of that principle.

---

### Quick-cite cheat sheet by report section
- *Related Work / multi-agent design:* [1][2][3][4][5]
- *Self-correction & structured output:* [6][7][8][9]
- *ABSA method:* [14][15][16][17]
- *Reasoning agent:* [18][19][20]
- *Evaluation (LLM-judge + metrics):* [10][11][21]
- *Threats to Validity (judge bias):* [12][13]
- *Dataset:* [22] + Yelp Open Dataset page
