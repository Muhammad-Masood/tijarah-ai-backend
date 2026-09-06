"""Daraz SEO Keyword Analysis Service.

Builds a catalog of competing products from Daraz's public search, filters
by adaptive semantic relevance (percentile-based, not fixed threshold),
mines candidate keywords via hybrid NLP (TF-IDF) + LLM, clusters keywords
by embedding similarity to discover buyer intents, builds a product-keyword
bipartite graph with community detection, and scores keyword clusters by
relevance vs. competition to surface winning SEO keywords.

Pipeline:
  1. Extract seed keywords from user's product (LLM + NLP)
  2. Build initial catalog by searching Daraz with seed keywords
  3. Filter catalog by adaptive embedding similarity (percentile-based)
  4. Mine candidate keywords from filtered catalog titles (TF-IDF + LLM)
  5. Cluster keywords by embedding similarity (discover buyer intents)
  6. Build product-keyword bipartite graph + community detection
  7. Score keyword clusters: (relevance * cluster_bonus) / log2(competition + 2)
  8. Iteratively expand catalog with top-scoring new clusters
  9. Track products appearing across 3+ keyword clusters separately
"""

import json
import logging
import math
import re
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from openai import OpenAI
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS as _SKLEARN_EN_STOP, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from neurocom_backend.services.daraz_catalog_service import scrape_products_by_category

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenAI clients — embeddings via OpenAI API, LLM via OpenRouter
# ---------------------------------------------------------------------------

_embedding_client: Optional[OpenAI] = None
_llm_client: Optional[OpenAI] = None


def _get_embedding_client() -> OpenAI:
    """Lazy-init OpenAI client for embeddings. Uses OPENAI_API_KEY."""
    global _embedding_client
    if _embedding_client is None:
        import os
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            # Fall back to OpenRouter which also supports text-embedding-3-small
            api_key = os.getenv("OPEN_ROUTER_AI_API_KEY")
            _embedding_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            )
        else:
            _embedding_client = OpenAI(api_key=api_key)
    return _embedding_client


def _get_llm_client() -> OpenAI:
    """Lazy-init OpenAI-compatible client for LLM calls. Uses OpenRouter."""
    global _llm_client
    if _llm_client is None:
        import os
        api_key = os.getenv("OPEN_ROUTER_AI_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = "https://openrouter.ai/api/v1" if os.getenv("OPEN_ROUTER_AI_API_KEY") else None
        _llm_client = OpenAI(base_url=base_url, api_key=api_key) if base_url else OpenAI(api_key=api_key)
    return _llm_client


_LLM_MODEL = "gpt-4o-mini-2024-07-18"
_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_BATCH_SIZE = 100


# ---------------------------------------------------------------------------
# Step 1: Seed keyword extraction
# ---------------------------------------------------------------------------

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "this", "that", "new", "hot",
    "sale", "free", "best", "top", "cheap", "premium", "high", "quality",
}

# RAKE needs a broader stopword list so marketing filler and connector words
# act as phrase boundaries (otherwise unrelated product nouns glue together).
# sklearn's ENGLISH_STOP_WORDS is already a dependency — extend it with
# marketplace-specific noise terms that appear in Daraz titles/descriptions.
_RAKE_STOP_WORDS: Set[str] = (
    set(_SKLEARN_EN_STOP) | _STOP_WORDS | {
        "pcs", "pack", "packs", "pieces", "piece", "set", "sets",
        "size", "sizes", "color", "colour", "colors", "colours",
        "mins", "minutes", "hours", "days", "day", "week", "weeks",
        "type", "types", "kind", "using", "used", "uses", "use",
        "per", "each", "item", "items", "product", "products",
        "your", "yours", "my", "our", "we", "they", "them",
    }
)


def _extract_nlp_keywords(
    text: str,
    top_n: int = 10,
    min_phrase_len: int = 2,
    max_phrase_len: int = 4,
) -> List[str]:
    """RAKE (Rapid Automatic Keyword Extraction) — order-preserving phrases.

    Splits the text on punctuation + stopwords to build candidate phrases,
    scores each word by degree(w)/frequency(w) across all candidates, sums
    those scores per phrase, and returns the top-N phrases.

    Unlike naive adjacent-bigram counting, this never emits reversed garbage
    like 'belt face' because candidates are always contiguous spans from the
    source text. Keyword-stuffed titles longer than max_phrase_len are
    broken into overlapping 2..max_phrase_len sliding windows, and shorter
    phrases that are substrings of an already-selected higher-scoring phrase
    are dropped.

    No new deps — runs locally in microseconds using sklearn's built-in
    English stopword list."""
    if not text:
        return []

    text_lower = text.lower()
    # Split on punctuation only (not whitespace) — punctuation acts as a
    # hard phrase boundary so 'Belt. Face' never merges into 'belt face',
    # while regular word spaces are preserved for phrase construction.
    segments = re.split(r"[^\w\s]+", text_lower)

    # Build raw candidate phrases by splitting each segment on stopwords.
    raw_candidates: List[List[str]] = []
    for seg in segments:
        current: List[str] = []
        for w in seg.split():
            if not w or len(w) <= 2 or w in _RAKE_STOP_WORDS:
                if current:
                    raw_candidates.append(current)
                    current = []
            else:
                current.append(w)
        if current:
            raw_candidates.append(current)

    if not raw_candidates:
        return []

    # Cap candidate length — Daraz titles are often unbroken keyword lists.
    # For a long phrase like ['face','slimming','belt','v','shape','jawline',
    # 'lifting','double','chin','reducer'] we emit every contiguous 2-4 gram
    # as its own candidate so 'face slimming belt' and 'double chin reducer'
    # both surface, while the 10-word blob is discarded.
    candidates: List[List[str]] = []
    for phrase in raw_candidates:
        if len(phrase) < min_phrase_len:
            # Singletons are still kept as low-value candidates.
            candidates.append(phrase)
            continue
        if len(phrase) <= max_phrase_len:
            candidates.append(phrase)
        else:
            for size in range(min_phrase_len, max_phrase_len + 1):
                for i in range(len(phrase) - size + 1):
                    candidates.append(phrase[i:i + size])

    # RAKE word scores: degree(w) = sum of lengths of phrases containing w,
    # freq(w) = number of phrases containing w. Common-but-connected words
    # score low; rare words that appear in long phrases score high.
    freq: Counter = Counter()
    degree: Counter = Counter()
    for phrase in candidates:
        phrase_len = len(phrase)
        for w in phrase:
            freq[w] += 1
            degree[w] += phrase_len

    word_score = {w: degree[w] / freq[w] for w in freq}

    phrase_scores: Dict[str, float] = {}
    phrase_len_map: Dict[str, int] = {}
    for phrase in candidates:
        key = " ".join(phrase)
        if key in phrase_scores:
            continue
        phrase_scores[key] = sum(word_score[w] for w in phrase)
        phrase_len_map[key] = len(phrase)

    # Sort by score desc, then by length desc so ties prefer multi-word phrases.
    ranked = sorted(
        phrase_scores.items(),
        key=lambda kv: (kv[1], phrase_len_map[kv[0]]),
        reverse=True,
    )

    # Greedy dedupe: skip a phrase if it is already contained as a whole-word
    # substring of a higher-ranked phrase we've selected.
    result: List[str] = []
    for phrase, _ in ranked:
        if any(
            phrase == existing or f" {phrase} " in f" {existing} "
            for existing in result
        ):
            continue
        result.append(phrase)
        if len(result) >= top_n:
            break

    return result


def _extract_seed_keywords(title: str, description: Optional[str]) -> List[dict]:
    """Hybrid extraction: LLM for semantic keywords + NLP for statistical terms.
    Returns list of {"keyword": str, "source": str}."""
    keywords = []
    seen = set()

    print("title: ", title, "desc: ", description)
    # NLP track — fast, free, catches terms the LLM might skip
    nlp_terms = _extract_nlp_keywords(title)
    if description:
        nlp_terms.extend(_extract_nlp_keywords(description, top_n=5))
    for term in nlp_terms:
        if term not in seen:
            seen.add(term)
            keywords.append({"keyword": term, "source": "nlp"})

    print("nlp keywords: ", keywords)
    # LLM track — semantic understanding of product type, use-case, audience
    try:
        client = _get_llm_client()
        desc_snippet = (description or "")[:500]
        prompt = (
            f"You are a Daraz.pk SEO expert. Given this product, extract 6-8 search keywords "
            f"that a buyer would type to find it. Include:\n"
            f"- Product type keywords (e.g. 'floor lamp', 'standing lamp')\n"
            f"- Attribute-based keywords (e.g. 'wooden lamp', 'LED black lamp')\n"
            f"- Use-case keywords (e.g. 'living room lamp', 'corner lighting')\n\n"
            f"Product title: {title}\n"
            f"Product description: {desc_snippet}\n\n"
            f"Return ONLY a JSON array of strings, e.g. [\"floor lamp\", \"wooden standing lamp\"]"
        )
        response = client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        llm_keywords = json.loads(content)
        print("llm keywords: ", llm_keywords)
        if isinstance(llm_keywords, list):
            for kw in llm_keywords:
                kw_str = str(kw).strip().lower()
                if kw_str and kw_str not in seen and len(kw_str) > 2:
                    seen.add(kw_str)
                    keywords.append({"keyword": kw_str, "source": "llm"})
    except Exception as e:
        logger.warning("LLM seed keyword extraction failed: %s", e)

    return keywords[:12]


# ---------------------------------------------------------------------------
# Step 2: Catalog building
# ---------------------------------------------------------------------------

def _build_catalog_from_keywords(
    keywords: List[str],
    max_pages_per_keyword: int = 2,
    existing_catalog: Optional[Dict[str, dict]] = None,
) -> Tuple[Dict[str, dict], Dict[str, int]]:
    """Search Daraz catalog with each keyword. Returns:
    - catalog: dict of item_id -> product dict (with keyword_sources)
    - competition: dict of keyword -> filteredQuatity (total listings)
    """
    catalog = dict(existing_catalog) if existing_catalog else {}
    competition: Dict[str, int] = {}

    for kw in keywords:
        try:
            result = scrape_products_by_category(query=kw, page=1, max_pages=max_pages_per_keyword)
        except Exception as e:
            logger.warning("Catalog search failed for keyword '%s': %s", kw, e)
            continue

        competition[kw] = result.get("total_products", 0) * result.get("total_pages", 0)

        for product in result.get("products", []):
            pid = str(product.get("nid", product.get("itemId", "")))
            if not pid:
                continue
            if pid in catalog:
                if kw not in catalog[pid].get("keyword_sources", []):
                    catalog[pid]["keyword_sources"] = catalog[pid].get("keyword_sources", []) + [kw]
            else:
                product["keyword_sources"] = [kw]
                catalog[pid] = product

        time.sleep(0.5)

    return catalog, competition


# ---------------------------------------------------------------------------
# Step 3: Adaptive embedding-based filtering (percentile threshold)
# ---------------------------------------------------------------------------

def _get_embeddings(texts: List[str]) -> np.ndarray:
    """Get embeddings for a list of texts. Batches to avoid API limits."""
    if not texts:
        return np.array([])

    client = _get_embedding_client()
    all_embeddings = []

    for i in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + _EMBEDDING_BATCH_SIZE]
        cleaned = [t.replace("\x00", "")[:2000] for t in batch]
        response = client.embeddings.create(input=cleaned, model=_EMBEDDING_MODEL)
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

    return np.array(all_embeddings)


def _filter_by_adaptive_similarity(
    user_text: str,
    catalog: Dict[str, dict],
    percentile: int = 75,
    min_threshold: float = 0.60,
    max_threshold: float = 0.90,
) -> Tuple[Dict[str, dict], np.ndarray]:
    """Filter catalog products using adaptive threshold.

    Instead of a fixed 0.75 cutoff, computes all similarities and uses
    the given percentile as the threshold — clamped between min_threshold
    and max_threshold to avoid extremes.

    This handles niche variation: 'Women's Summer Dress' vs 'Women's Floral
    Dress' might score 0.71 (same family) while 'Face Slimming Belt' vs
    'Face Lift Strap' scores 0.82. The percentile adapts to the distribution.
    """
    user_embedding = _get_embeddings([user_text])

    product_ids = list(catalog.keys())
    product_texts = [catalog[pid].get("name", "") for pid in product_ids]

    if not product_texts:
        return {}, user_embedding

    product_embeddings = _get_embeddings(product_texts)
    similarities = cosine_similarity(user_embedding, product_embeddings)[0]

    # Adaptive threshold: percentile of the similarity distribution
    raw_threshold = float(np.percentile(similarities, percentile))
    threshold = max(min_threshold, min(max_threshold, raw_threshold))

    logger.info(
        "Adaptive filter: percentile=%d raw=%.3f clamped=%.3f (range %.3f-%.3f)",
        percentile, raw_threshold, threshold,
        float(similarities.min()), float(similarities.max()),
    )

    filtered = {}
    for idx, pid in enumerate(product_ids):
        if similarities[idx] >= threshold:
            catalog[pid]["_similarity"] = float(similarities[idx])
            filtered[pid] = catalog[pid]

    logger.info(
        "Embedding filter: %d/%d products passed threshold %.3f",
        len(filtered), len(catalog), threshold,
    )
    return filtered, user_embedding


# ---------------------------------------------------------------------------
# Step 4: Keyword mining from catalog
# ---------------------------------------------------------------------------

def _mine_keywords_from_catalog(
    catalog: Dict[str, dict],
    user_title: str,
    top_n_tfidf: int = 30,
    top_n_titles: int = 20,
) -> List[str]:
    """Mine candidate keywords from catalog product titles using:
    1. TF-IDF n-gram extraction (local, fast)
    2. LLM long-tail keyword generation (single call)
    Returns deduplicated list of candidate keywords.
    """
    candidates = []
    seen = set()

    # --- Track A: TF-IDF n-grams ---
    titles = [p.get("name", "") for p in catalog.values() if p.get("name")]
    if titles:
        vectorizer = TfidfVectorizer(
            ngram_range=(1, 3),
            max_features=500,
            stop_words="english",
            min_df=2,
            max_df=0.8,
        )
        try:
            tfidf_matrix = vectorizer.fit_transform(titles)
            feature_names = vectorizer.get_feature_names_out()
            mean_scores = np.asarray(tfidf_matrix.mean(axis=0)).flatten()
            top_indices = mean_scores.argsort()[::-1][:top_n_tfidf]
            for idx in top_indices:
                term = str(feature_names[idx]).strip()
                if term and len(term) > 2 and term not in seen:
                    seen.add(term)
                    candidates.append(term)
        except ValueError as e:
            logger.warning("TF-IDF extraction failed (empty vocabulary?): %s", e)

    # --- Track B: LLM long-tail generation (single call) ---
    sorted_products = sorted(
        catalog.values(),
        key=lambda p: p.get("_similarity", 0),
        reverse=True,
    )
    top_titles = [p.get("name", "") for p in sorted_products[:top_n_titles]]

    if top_titles:
        try:
            client = _get_llm_client()
            titles_str = "\n".join(f"{i+1}. {t}" for i, t in enumerate(top_titles))
            tfidf_str = ", ".join(candidates[:15]) if candidates else "none"

            prompt = (
                f"You are a Daraz.pk SEO expert. Given these product titles from a catalog "
                f"related to '{user_title}', and these already-extracted terms: [{tfidf_str}]\n\n"
                f"Top catalog titles:\n{titles_str}\n\n"
                f"Suggest 15-20 long-tail search keywords (2-5 words each) that buyers would "
                f"use on Daraz.pk. Focus on:\n"
                f"- Attribute combinations (e.g. 'wooden arc floor lamp')\n"
                f"- Use-case phrases (e.g. 'lamp for living room corner')\n"
                f"- Style-based terms (e.g. 'modern minimalist standing lamp')\n\n"
                f"Return ONLY a JSON array of strings."
            )
            response = client.chat.completions.create(
                model=_LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=400,
            )
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            llm_keywords = json.loads(content)
            if isinstance(llm_keywords, list):
                for kw in llm_keywords:
                    kw_str = str(kw).strip().lower()
                    if kw_str and kw_str not in seen and len(kw_str) > 2:
                        seen.add(kw_str)
                        candidates.append(kw_str)
        except Exception as e:
            logger.warning("LLM keyword mining failed: %s", e)

    return candidates[:40]


# ---------------------------------------------------------------------------
# Step 5: Keyword clustering via embeddings (discover buyer intents)
# ---------------------------------------------------------------------------

def _cluster_keywords(
    keywords: List[str],
    similarity_threshold: float = 0.82,
) -> List[dict]:
    """Cluster candidate keywords by embedding similarity.

    Keywords like 'face slimming belt', 'jawline shaper', 'double chin reducer'
    are lexically different but semantically identical. Clustering groups them
    into a single buyer intent, then we score the cluster — not each keyword.

    Returns list of clusters: [{representative, members, avg_embedding, size}]
    """
    if not keywords:
        return []

    embeddings = _get_embeddings(keywords)
    sim_matrix = cosine_similarity(embeddings)

    assigned = [False] * len(keywords)
    clusters = []

    for i in range(len(keywords)):
        if assigned[i]:
            continue
        cluster_members = [i]
        assigned[i] = True
        for j in range(i + 1, len(keywords)):
            if not assigned[j] and sim_matrix[i][j] >= similarity_threshold:
                cluster_members.append(j)
                assigned[j] = True

        member_keywords = [keywords[idx] for idx in cluster_members]
        avg_embedding = embeddings[cluster_members].mean(axis=0)

        # Pick the shortest keyword as representative (cleanest for SEO)
        representative = min(member_keywords, key=len)

        clusters.append({
            "representative": representative,
            "members": member_keywords,
            "avg_embedding": avg_embedding,
            "size": len(member_keywords),
        })

    clusters.sort(key=lambda c: c["size"], reverse=True)
    logger.info(
        "Keyword clustering: %d keywords -> %d clusters (threshold=%.2f)",
        len(keywords), len(clusters), similarity_threshold,
    )
    return clusters


# ---------------------------------------------------------------------------
# Step 6: Product-keyword bipartite graph + community detection
# ---------------------------------------------------------------------------

def _build_product_keyword_graph(
    catalog: Dict[str, dict],
    keyword_clusters: List[dict],
) -> Dict[str, Any]:
    """Build a bipartite product<->keyword graph and run label-propagation
    community detection.

    Instead of flat keyword->product mapping, this discovers natural niche
    clusters: products that share multiple keyword clusters belong to the
    same community. This reveals sub-niches the merchant might not have
    considered.

    Returns: {communities: [{id, products, keywords, size}]}
    """
    # Build adjacency: product_id <-> cluster_representative
    product_to_clusters: Dict[str, Set[str]] = defaultdict(set)
    cluster_to_products: Dict[str, Set[str]] = defaultdict(set)

    for cluster in keyword_clusters:
        rep = cluster["representative"]
        members = set(cluster["members"])
        for pid, product in catalog.items():
            title_lower = product.get("name", "").lower()
            for kw in members:
                if kw in title_lower:
                    product_to_clusters[pid].add(rep)
                    cluster_to_products[rep].add(pid)
                    break

    # Label propagation community detection
    # Each node starts with its own label, then iteratively adopts the
    # most common label among its neighbors.
    all_nodes = set(product_to_clusters.keys()) | set(f"kw:{r}" for r in cluster_to_products)
    labels = {node: i for i, node in enumerate(all_nodes)}

    for _iteration in range(10):
        changed = False
        for node in all_nodes:
            neighbor_labels = []
            if node.startswith("kw:"):
                rep = node[3:]
                for pid in cluster_to_products.get(rep, set()):
                    neighbor_labels.append(labels[pid])
            else:
                for cluster_rep in product_to_clusters.get(node, set()):
                    neighbor_labels.append(labels[f"kw:{cluster_rep}"])

            if not neighbor_labels:
                continue

            label_counts = Counter(neighbor_labels)
            best_label = label_counts.most_common(1)[0][0]
            if labels[node] != best_label:
                labels[node] = best_label
                changed = True

        if not changed:
            break

    # Extract communities (only product nodes, grouped by label)
    label_to_products: Dict[int, List[str]] = defaultdict(list)
    label_to_keywords: Dict[int, Set[str]] = defaultdict(set)
    for node, label in labels.items():
        if not node.startswith("kw:"):
            label_to_products[label].append(node)
            for cluster_rep in product_to_clusters.get(node, set()):
                label_to_keywords[label].add(cluster_rep)

    communities = []
    for label in sorted(label_to_products.keys()):
        products = label_to_products[label]
        if len(products) < 2:
            continue
        communities.append({
            "id": label,
            "products": products,
            "keywords": sorted(label_to_keywords.get(label, set())),
            "size": len(products),
        })

    communities.sort(key=lambda c: c["size"], reverse=True)
    logger.info("Community detection: %d communities found", len(communities))
    return {"communities": communities}


# ---------------------------------------------------------------------------
# Step 7: Keyword cluster scoring
# ---------------------------------------------------------------------------

def _score_keyword_clusters(
    clusters: List[dict],
    catalog: Dict[str, dict],
    user_embedding: np.ndarray,
    competition: Dict[str, int],
    already_scored: Optional[Set[str]] = None,
) -> List[dict]:
    """Score each keyword CLUSTER (not individual keyword) by:
    - relevance: avg cosine similarity of catalog products matching any
      keyword in the cluster
    - competition: total Daraz listings for the representative keyword
    - winning_score: (relevance * cluster_bonus) / log2(competition + 2)
    - cluster_strength bonus: more synonyms = stronger buyer intent signal

    Skips clusters whose representative is in already_scored.
    """
    scored = []
    skip = already_scored or set()

    product_ids = list(catalog.keys())
    product_titles = [catalog[pid].get("name", "") for pid in product_ids]

    if not product_titles:
        return []

    product_embeddings = _get_embeddings(product_titles)
    similarities_to_user = cosine_similarity(user_embedding, product_embeddings)[0]

    for cluster in clusters:
        rep = cluster["representative"]
        if rep in skip:
            continue

        members = set(cluster["members"])

        # Find catalog products matching ANY keyword in the cluster
        matching_indices = []
        for idx, title in enumerate(product_titles):
            title_lower = title.lower()
            matched = False
            for kw in members:
                if kw in title_lower:
                    matched = True
                    break
            if not matched:
                # Check word overlap as fallback
                title_words = set(title_lower.split())
                for kw in members:
                    kw_words = set(kw.split())
                    overlap = len(kw_words & title_words) / max(len(kw_words), 1)
                    if overlap >= 0.5:
                        matched = True
                        break
            if matched:
                matching_indices.append(idx)

        if not matching_indices:
            continue

        matching_sims = [similarities_to_user[i] for i in matching_indices]
        relevance = float(np.mean(matching_sims))

        comp_count = competition.get(rep, len(matching_indices) * 10)

        # Cluster strength bonus: more synonyms = stronger intent signal
        cluster_bonus = 1.0 + (0.1 * (cluster["size"] - 1))

        winning_score = (relevance * 100 * cluster_bonus) / math.log2(comp_count + 2)

        match_with_sim = sorted(
            zip(matching_indices, matching_sims), key=lambda x: x[1], reverse=True
        )
        examples = [
            product_titles[idx][:80]
            for idx, _ in match_with_sim[:3]
        ]

        scored.append({
            "keyword": rep,
            "keyword_variants": [m for m in cluster["members"] if m != rep],
            "relevance_score": round(relevance, 4),
            "competition_count": comp_count,
            "winning_score": round(winning_score, 4),
            "matching_products": len(matching_indices),
            "cluster_size": cluster["size"],
            "example_products": examples,
        })

    scored.sort(key=lambda x: x["winning_score"], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Step 8: Iterative expansion
# ---------------------------------------------------------------------------

def _iterative_expand(
    catalog: Dict[str, dict],
    scored_clusters: List[dict],
    competition: Dict[str, int],
    user_embedding: np.ndarray,
    user_title: str,
    max_iterations: int = 4,
    clusters_per_iteration: int = 5,
) -> Tuple[Dict[str, dict], List[dict], Dict[str, int], int]:
    """Expand catalog by searching top unexplored keyword clusters iteratively.
    Uses adaptive threshold for new product filtering and re-clusters new
    keywords in each iteration.
    """
    all_scored = list(scored_clusters)
    explored = {s["keyword"] for s in all_scored}
    iterations = 0

    for iteration in range(max_iterations):
        # Pick top unexplored clusters — search representative + variants
        unexplored = [s for s in all_scored if s["keyword"] not in explored]
        top_new = []
        for s in unexplored[:clusters_per_iteration]:
            top_new.append(s["keyword"])
            top_new.extend(s.get("keyword_variants", [])[:2])

        if not top_new:
            logger.info("Iteration %d: no new keywords to explore, stopping", iteration + 1)
            break

        logger.info("Iteration %d: searching %d new keywords", iteration + 1, len(top_new))
        prev_size = len(catalog)

        new_catalog, new_competition = _build_catalog_from_keywords(
            keywords=top_new,
            max_pages_per_keyword=2,
            existing_catalog=catalog,
        )
        competition.update(new_competition)

        # Filter new products by adaptive embedding similarity
        new_product_ids = set(new_catalog.keys()) - set(catalog.keys())
        if new_product_ids:
            new_texts = [new_catalog[pid].get("name", "") for pid in new_product_ids]
            new_embeddings = _get_embeddings(new_texts)
            sims = cosine_similarity(user_embedding, new_embeddings)[0]
            # Adaptive threshold per iteration
            threshold = float(np.percentile(sims, 75)) if len(sims) > 5 else 0.70
            threshold = max(0.60, min(0.90, threshold))
            for idx, pid in enumerate(new_product_ids):
                if sims[idx] >= threshold:
                    new_catalog[pid]["_similarity"] = float(sims[idx])
                    catalog[pid] = new_catalog[pid]

        # Re-mine keywords from expanded catalog
        new_candidates = _mine_keywords_from_catalog(catalog, user_title, top_n_tfidf=20)
        unsearched = [kw for kw in new_candidates if kw not in explored]

        # Cluster and score new candidates
        if unsearched:
            new_clusters = _cluster_keywords(unsearched)
            new_scored = _score_keyword_clusters(
                new_clusters, catalog, user_embedding, competition, already_scored=explored,
            )
            all_scored.extend(new_scored)
            explored.update(c["representative"] for c in new_clusters)

        all_scored.sort(key=lambda x: x["winning_score"], reverse=True)

        iterations += 1
        added = len(catalog) - prev_size
        logger.info("Iteration %d: added %d products", iteration + 1, added)

        if added == 0 and not unsearched:
            logger.info("Iteration %d: no new products or keywords, stopping early", iteration + 1)
            break

    return catalog, all_scored, competition, iterations


# ---------------------------------------------------------------------------
# Step 9: Repeat product tracking
# ---------------------------------------------------------------------------

def _track_repeat_products(
    catalog: Dict[str, dict], min_appearances: int = 3
) -> List[dict]:
    """Find products that appear across 3+ keyword searches.
    These are strong competitors or keyword-stuffed listings."""
    repeats = []
    for pid, product in catalog.items():
        sources = product.get("keyword_sources", [])
        if len(sources) >= min_appearances:
            repeats.append({
                "item_id": pid,
                "name": product.get("name", "")[:100],
                "image": product.get("image", ""),
                "url": product.get("itemUrl", ""),
                "review": product.get("review", ""),
                "ratingScore": product.get("ratingScore", ""),
                "unitSold": product.get("itemSoldCntShow", "").strip(" "),
                "appearance_count": len(sources),
                "keywords_matched": sources,
            })
    repeats.sort(key=lambda x: x["appearance_count"], reverse=True)
    return repeats


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def analyze_keywords_for_product(
    item_id: int,
    access_token: str,
    max_iterations: int = 4,
    max_catalog_size: int = 500,
) -> dict:
    """Full keyword analysis pipeline for a merchant's product.

    1. Fetch user's product from Daraz API
    2. Extract seed keywords (LLM + NLP)
    3. Build initial catalog from seed keywords
    4. Filter by adaptive embedding similarity (percentile-based)
    5. Mine candidate keywords (TF-IDF + LLM)
    6. Cluster keywords by embedding similarity (discover buyer intents)
    7. Build product-keyword graph + community detection
    8. Score keyword clusters by relevance vs competition
    9. Iteratively expand catalog and re-score
    10. Track repeat products
    """
    from neurocom_backend.services.daraz_service import get_product_by_id

    # --- Fetch user's product ---
    logger.info("Keyword analysis: fetching product %d", item_id)
    product_response = get_product_by_id(item_id, access_token)
    product_data = product_response.data if hasattr(product_response, "data") else product_response.get("data", {})

    attrs = product_data.attributes if hasattr(product_data, "attributes") else {}
    title = attrs.name_en or "" if hasattr(attrs, "name_en") else product_data.get("attributes", {}).get("name_en", "")
    description = attrs.description_en or "" if hasattr(attrs, "description_en") else product_data.get("attributes", {}).get("description_en", "")

    user_text = f"{title} {description}".strip()
    if not user_text:
        raise ValueError(f"Product {item_id} has no title or description to analyze")

    user_product_info = {
        "item_id": item_id,
        "title": title,
        "description": (description or "")[:300],
        "price": None,
        "category": product_data.primary_category if hasattr(product_data, "primary_category") else None,
    }

    # --- Step 1: Seed keywords ---
    logger.info("Step 1: Extracting seed keywords")
    seed_keywords = _extract_seed_keywords(title, description)
    seed_kw_strings = [kw["keyword"] for kw in seed_keywords]
    logger.info("Seed keywords: %s", seed_kw_strings)

    # --- Step 2: Build initial catalog ---
    logger.info("Step 2: Building initial catalog from %d seed keywords", len(seed_kw_strings))
    catalog, competition = _build_catalog_from_keywords(seed_kw_strings, max_pages_per_keyword=3)
    logger.info("Initial catalog: %d products", len(catalog))

    # Cap catalog size
    if len(catalog) > max_catalog_size:
        sorted_catalog = sorted(
            catalog.values(),
            key=lambda p: (float(p.get("ratingScore", 0) or 0), int(p.get("review", 0) or 0)),
            reverse=True,
        )
        catalog = {p.get("nid", p.get("itemId", "")): p for p in sorted_catalog[:max_catalog_size]}

    # --- Step 3: Adaptive embedding filter ---
    logger.info("Step 3: Filtering by adaptive embedding similarity (percentile=75)")
    filtered_catalog, user_embedding = _filter_by_adaptive_similarity(user_text, catalog, percentile=75)
    logger.info("Relevant products after filtering: %d", len(filtered_catalog))

    if len(filtered_catalog) < 5:
        logger.warning("Very few relevant products (%d). Lowering percentile to 60", len(filtered_catalog))
        filtered_catalog, user_embedding = _filter_by_adaptive_similarity(user_text, catalog, percentile=60)

    # --- Step 4: Mine keywords ---
    logger.info("Step 4: Mining keywords from %d relevant products", len(filtered_catalog))
    candidate_keywords = _mine_keywords_from_catalog(filtered_catalog, title)
    logger.info("Candidate keywords mined: %d", len(candidate_keywords))

    # --- Step 5: Cluster keywords by embedding similarity ---
    logger.info("Step 5: Clustering %d candidate keywords", len(candidate_keywords))
    keyword_clusters = _cluster_keywords(candidate_keywords, similarity_threshold=0.82)
    logger.info("Keyword clusters: %d", len(keyword_clusters))

    # --- Step 6: Build product-keyword graph + community detection ---
    logger.info("Step 6: Building product-keyword graph + community detection")
    graph_result = _build_product_keyword_graph(filtered_catalog, keyword_clusters)
    communities = graph_result.get("communities", [])

    # --- Step 7: Score keyword clusters ---
    logger.info("Step 7: Scoring %d keyword clusters", len(keyword_clusters))
    scored_clusters = _score_keyword_clusters(keyword_clusters, filtered_catalog, user_embedding, competition)
    logger.info("Scored clusters: %d", len(scored_clusters))

    # --- Step 8: Iterative expansion ---
    logger.info("Step 8: Iterative expansion (max %d iterations)", max_iterations)
    filtered_catalog, all_scored, competition, iterations_run = _iterative_expand(
        catalog=filtered_catalog,
        scored_clusters=scored_clusters,
        competition=competition,
        user_embedding=user_embedding,
        user_title=title,
        max_iterations=max_iterations,
    )

    # --- Step 9: Track repeat products ---
    repeat_products = _track_repeat_products(filtered_catalog)

    # --- Build response ---
    total_catalog = len(filtered_catalog)
    winning_keywords = [
        {
            "keyword": s["keyword"],
            "keyword_variants": s.get("keyword_variants", []),
            "relevance_score": s["relevance_score"],
            "competition_count": s["competition_count"],
            "winning_score": s["winning_score"],
            "matching_products": s["matching_products"],
            "cluster_size": s.get("cluster_size", 1),
            "example_products": s["example_products"],
        }
        for s in all_scored[:50]  # Top 50 keyword clusters
    ]

    return {
        "user_product": user_product_info,
        "seed_keywords": seed_keywords,
        "total_catalog_size": total_catalog,
        "total_relevant_products": total_catalog,
        "winning_keywords": winning_keywords,
        "repeat_products": repeat_products,
        "iterations_run": iterations_run,
    }


def analyze_keywords_for_product_stream(
    item_id: int,
    access_token: str,
    max_iterations: int = 4,
    max_catalog_size: int = 500,
):
    """Streaming variant of analyze_keywords_for_product.

    Yields (event, data) pairs at each pipeline stage with full renderable
    data so the UI can display each section as it completes.
    """
    from neurocom_backend.services.daraz_service import get_product_by_id

    # --- Fetch user's product ---
    yield "progress", {"stage": "fetching_product", "message": "Fetching your product from Daraz..."}
    product_response = get_product_by_id(item_id, access_token)
    product_data = product_response.data if hasattr(product_response, "data") else product_response.get("data", {})

    attrs = product_data.attributes if hasattr(product_data, "attributes") else {}
    title = attrs.name_en or "" if hasattr(attrs, "name_en") else product_data.get("attributes", {}).get("name_en", "")
    description = attrs.description_en or "" if hasattr(attrs, "description_en") else product_data.get("attributes", {}).get("description_en", "")

    user_text = f"{title} {description}".strip()
    if not user_text:
        raise ValueError(f"Product {item_id} has no title or description to analyze")

    user_product_info = {
        "item_id": item_id,
        "title": title,
        "description": (description or "")[:300],
        "price": None,
        "category": product_data.primary_category if hasattr(product_data, "primary_category") else None,
    }
    yield "product_fetched", {"user_product": user_product_info}

    # --- Step 1: Seed keywords ---
    yield "progress", {"stage": "extracting_seed_keywords", "message": "Extracting seed keywords via LLM + NLP..."}
    seed_keywords = _extract_seed_keywords(title, description)
    yield "seed_keywords", {
        "seed_keywords": seed_keywords,
        "count": len(seed_keywords),
    }

    # --- Step 2: Build initial catalog ---
    seed_kw_strings = [kw["keyword"] for kw in seed_keywords]
    yield "progress", {"stage": "building_catalog", "message": f"Scanning Daraz catalog for {len(seed_kw_strings)} seed keywords..."}
    catalog, competition = _build_catalog_from_keywords(seed_kw_strings, max_pages_per_keyword=3)

    if len(catalog) > max_catalog_size:
        sorted_catalog = sorted(
            catalog.values(),
            key=lambda p: (float(p.get("ratingScore", 0) or 0), int(p.get("review", 0) or 0)),
            reverse=True,
        )
        catalog = {p.get("nid", p.get("itemId", "")): p for p in sorted_catalog[:max_catalog_size]}

    yield "catalog_built", {
        "total_catalog_size": len(catalog),
        "competition_data": {k: v for k, v in sorted(competition.items(), key=lambda x: x[1], reverse=True)},
    }

    # --- Step 3: Adaptive embedding filter ---
    yield "progress", {"stage": "filtering_by_similarity", "message": "Filtering products by semantic relevance..."}
    filtered_catalog, user_embedding = _filter_by_adaptive_similarity(user_text, catalog, percentile=75)
    percentile_used = 75

    if len(filtered_catalog) < 5:
        filtered_catalog, user_embedding = _filter_by_adaptive_similarity(user_text, catalog, percentile=60)
        percentile_used = 60

    relevant_products = [
        {
            "item_id": pid,
            "name": p.get("name", "")[:100],
            "price": p.get("price", ""),
            "image": p.get("image", ""),
            "rating_score": p.get("ratingScore"),
            "review_count": p.get("review"),
            "seller_name": p.get("sellerName"),
            "similarity": round(float(p.get("_similarity", 0)), 3),
        }
        for pid, p in sorted(filtered_catalog.items(), key=lambda x: float(x[1].get("_similarity", 0)), reverse=True)[:20]
    ]
    yield "similarity_filter_done", {
        "relevant_products_count": len(filtered_catalog),
        "percentile_used": percentile_used,
        "top_relevant_products": relevant_products,
    }

    # --- Step 4: Mine keywords ---
    yield "progress", {"stage": "mining_keywords", "message": f"Mining keywords from {len(filtered_catalog)} relevant products..."}
    candidate_keywords = _mine_keywords_from_catalog(filtered_catalog, title)
    yield "keywords_mined", {
        "candidate_keywords": candidate_keywords,
        "count": len(candidate_keywords),
    }

    # --- Step 5: Cluster keywords ---
    yield "progress", {"stage": "clustering_keywords", "message": f"Clustering {len(candidate_keywords)} keywords by semantic similarity..."}
    keyword_clusters = _cluster_keywords(candidate_keywords, similarity_threshold=0.82)
    yield "keywords_clustered", {
        "clusters": [
            {
                "representative": c["representative"],
                "members": c["members"],
                "size": c["size"],
            }
            for c in keyword_clusters
        ],
        "cluster_count": len(keyword_clusters),
    }

    # --- Step 6: Build product-keyword graph ---
    yield "progress", {"stage": "building_keyword_graph", "message": "Building product-keyword graph & detecting communities..."}
    graph_result = _build_product_keyword_graph(filtered_catalog, keyword_clusters)
    communities = graph_result.get("communities", [])
    yield "graph_built", {
        "communities": [
            {
                "id": c["id"],
                "keywords": c["keywords"],
                "product_count": c["size"],
            }
            for c in communities[:10]
        ],
        "community_count": len(communities),
    }

    # --- Step 7: Score keyword clusters ---
    yield "progress", {"stage": "scoring_clusters", "message": "Scoring keyword clusters by relevance vs competition..."}
    scored_clusters = _score_keyword_clusters(keyword_clusters, filtered_catalog, user_embedding, competition)
    yield "clusters_scored", {
        "top_scored": [
            {
                "keyword": s["keyword"],
                "keyword_variants": s.get("keyword_variants", []),
                "relevance_score": s["relevance_score"],
                "competition_count": s["competition_count"],
                "winning_score": s["winning_score"],
                "matching_products": s["matching_products"],
                "cluster_size": s.get("cluster_size", 1),
                "example_products": s["example_products"],
            }
            for s in scored_clusters[:15]
        ],
        "scored_count": len(scored_clusters),
    }

    # --- Step 8: Iterative expansion ---
    yield "progress", {"stage": "iterative_expansion", "message": f"Iterative expansion (max {max_iterations} rounds)..."}
    filtered_catalog, all_scored, competition, iterations_run = _iterative_expand(
        catalog=filtered_catalog,
        scored_clusters=scored_clusters,
        competition=competition,
        user_embedding=user_embedding,
        user_title=title,
        max_iterations=max_iterations,
    )
    yield "expansion_done", {
        "iterations_run": iterations_run,
        "final_catalog_size": len(filtered_catalog),
    }

    # --- Step 9: Track repeat products ---
    repeat_products = _track_repeat_products(filtered_catalog)

    # --- Build final response ---
    total_catalog = len(filtered_catalog)
    winning_keywords = [
        {
            "keyword": s["keyword"],
            "keyword_variants": s.get("keyword_variants", []),
            "relevance_score": s["relevance_score"],
            "competition_count": s["competition_count"],
            "winning_score": s["winning_score"],
            "matching_products": s["matching_products"],
            "cluster_size": s.get("cluster_size", 1),
            "example_products": s["example_products"],
        }
        for s in all_scored[:50]
    ]

    yield "result", {
        "user_product": user_product_info,
        "seed_keywords": seed_keywords,
        "total_catalog_size": total_catalog,
        "total_relevant_products": total_catalog,
        "winning_keywords": winning_keywords,
        "repeat_products": [
            {
                "item_id": rp["item_id"],
                "name": rp["name"],
                "image": rp["image"],
                "url": rp["url"],
                "review": rp["review"],
                "ratingScore": rp["ratingScore"],
                "unitSold": rp["unitSold"],
                "appearance_count": rp["appearance_count"],
                "keywords_matched": rp["keywords_matched"],
            }
            for rp in repeat_products
        ],
        "iterations_run": iterations_run,
    }
