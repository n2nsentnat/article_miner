# TODO

1. Improve LLM system and user prompts to include definition of each metric.
2. Make use of MeSH terms(Medical Subject Headings) for bucketing, explore possible use of MeSH in other places
3. List all validation criteria with short description and provide users with command line options to choose and relax rejection/human_review criteria.
4. Add Graph/Chart visualization for metrics 
5. SLM/BERT(on premise) for de-duplication and grouping
6. Add [Europe PMC](https://europepmc.org/) and other providers, provide command line option to choose provider. Note EuropePMC has pubMed articles as well. pubMed provides metadata with abstracts for free but entire article may not be freely accessible, in such cases we might get full article from EuropePMC, so both pubMed and EuropePMC can be used together.
7. Add more finding metrics.
8. LOW_PRIORITY: Current flow is a 3-stage pipeline (`fetch_and_store_data` → `cleanse_data` → `run_findings`) that can be executed as a single workflow. Analyse possibility of a single analysis tool (`fetch_from_pubmed` → `analyse_for_search_term`). **Note:** This requires maintaining a visited article hash to avoid duplicates, and an article ID–findings map to audit ground truths.
