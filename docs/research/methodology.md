# Research methodology

Snapshot date: 2026-08-06
Review type: structured scoping review, not a formal systematic review or meta-analysis

## Questions

1. Which measurements can validly describe prompt quality, conversation logic/flow, verified task completion, and software-delivery efficiency?
2. Which deterministic, statistical, and neural methods are appropriate for a local-first product?
3. How should model uncertainty, bias, privacy, and longitudinal confounding be handled?
4. Which integration surfaces can obtain Codex and Claude Code data without taking custody of credentials?
5. Which methods can improve delivery speed without optimizing a misleading proxy?

## Scope

The publication map covers:

- prompting and prompt optimization;
- LLM evaluation, factuality, and judges;
- AI-assisted software engineering and productivity;
- dialogue/generated-text quality;
- logic, argumentation, and coherence;
- sentiment, emotion, empathy, toxicity, and abuse;
- embeddings, clustering, and topic modeling;
- uncertainty, calibration, conformal prediction, and abstention;
- text privacy, PII anonymization, memorization, and differential privacy;
- efficient/local model inference;
- change detection, longitudinal analysis, and process mining;
- human factors, trust, workload, and productivity.

Current provider documentation and Hugging Face model cards inform the architecture/model shortlist but are not counted among the 131 academic publications.

## Discovery and verification

Candidate work was discovered through title/topic queries and citation chaining across primary publication surfaces. Included records were then title-matched against one of:

- arXiv;
- ACL Anthology;
- OpenReview;
- JMLR/JOSS;
- USENIX proceedings;
- NBER;
- NASA publications;
- a DOI resolver or the publisher's official landing page.

Stable arXiv, DOI, Anthology, proceedings, or publisher URLs were retained. Candidates with mismatched identifiers or unclear primary metadata were discarded. The final set contains 131 unique publications across 12 themes.

This first snapshot did not maintain a complete candidate/exclusion log, so it must not be described as PRISMA-complete. Future updates should keep a machine-readable search journal and exclusion reasons.

## Inclusion criteria

- Direct relevance to at least one product question.
- Primary paper/proceedings/book record with title and stable identifier verified.
- Foundational methods are allowed even when old.
- Preprints are allowed for fast-moving LLM topics and must remain labeled by their actual venue/status.
- Both positive and cautionary evidence are included.

## Exclusion criteria

- Marketing pages, unsourced blog claims, benchmark leaderboards without a method paper, or secondary summaries as academic evidence.
- Duplicate versions of the same work unless the versions materially differ.
- Publications whose identifier/title could not be verified.
- Methods unrelated to text/agent workflow analytics.
- A model card alone; model cards belong in the implementation shortlist and require their own license/provenance review.

## Evidence interpretation

The review does not rank papers by citation count or collapse heterogeneous studies into a meta-analytic effect. Instead, product decisions use an evidence ladder:

1. executable/provider facts and explicit human labels;
2. replicated task/domain benchmarks;
3. calibrated in-domain model results;
4. out-of-domain benchmark evidence;
5. exploratory model or self-reported model-card claims.

Software-engineering productivity studies are especially context-dependent. Completion time, accepted suggestions, lines changed, pull requests, and perceived productivity measure different constructs. None is a universal developer-performance measure.

## Reproducible update protocol

For each future publication, record:

```text
id, title, authors, year, venue, doi, arxiv_id, anthology_id, url,
theme, method, dataset, reported_metrics, product_relevance,
limitations, privacy_risk, verification_source, verified_at
```

For every review update:

1. Freeze the search date and query families.
2. Store candidate and exclusion records.
3. Deduplicate by DOI, then arXiv/Anthology ID, then normalized title.
4. Verify title/year/authors on a primary landing page.
5. Label preprint versus peer-reviewed venue accurately.
6. Re-resolve every link and retain stable identifiers.
7. Record which product decision changed, if any.
8. Benchmark implementation candidates on the project's domain set before changing defaults.

## Known gaps

- Limited empirical work directly evaluates prompts in long-running coding-agent conversations.
- Provider session formats and analytics surfaces evolve faster than the academic literature.
- General dialogue/sentiment datasets do not represent mixed code, shell output, and engineering shorthand.
- “Task completion” requires project-specific observable evidence; linguistic metrics cannot supply ground truth.
- Team analytics create governance and labor concerns not solved by technical pseudonymization alone.
- Polish/English mixed engineering conversations need a dedicated evaluation slice.

## Citation integrity

The bibliography in [research-journal.md](research-journal.md) uses concise author-year citations and primary links. Before publication claims are used in code comments, marketing, or a formal paper, the relevant paper should be read in full and its exact result/dataset/limitations recorded. This scoping map establishes coverage and direction; it does not authorize stronger claims than the papers support.
