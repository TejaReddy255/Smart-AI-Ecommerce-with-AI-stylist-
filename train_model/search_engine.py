from pathlib import Path
import numpy as np
import pandas as pd
import faiss
import torch
import open_clip
from typing import Dict, Tuple, List, Optional
import sys
import os
import re


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CSV_PATH = DATA_DIR / "styles.csv"
EMB_DIR = BASE_DIR / "embeddings"
IDX_DIR = BASE_DIR / "indexes"
FAISS_FILE = IDX_DIR / "faiss_clip.index"
IDX_FILE = EMB_DIR / "ids.npy"
MODEL_NAME = "ViT-B-32"
PRETRAINED = "openai"
DEVICE = "cpu"
FILTER_COLUMNS = ["baseColour", "masterCategory", "subCategory", "articleType", "gender"]


_model, _tokenizer, _index, _idmap, _catalog, _catalog_stats, _filter_patterns = (None,) * 7

def data_load():
    """Load all necessary data, models, and pre-compile fallback patterns."""
    global _model, _tokenizer, _index, _idmap, _catalog, _catalog_stats, _filter_patterns
    
    if _model is None:
        _model, _, _ = open_clip.create_model_and_transforms(MODEL_NAME, pretrained=PRETRAINED, device=DEVICE)
        _tokenizer = open_clip.get_tokenizer(MODEL_NAME)
        _model = _model.to(DEVICE).eval()
    if _index is None:
        if Path(FAISS_FILE).exists(): _index = faiss.read_index(str(FAISS_FILE))
        else: raise RuntimeError(f"Faiss index not found at {FAISS_FILE}. Run build_index().")
    if _idmap is None:
        if Path(IDX_FILE).exists(): _idmap = np.load(str(IDX_FILE), allow_pickle=True).astype(str)
        else: raise RuntimeError(f"ID map not found at {IDX_FILE}. Run build_index().")
    if _catalog is None:
        if Path(CSV_PATH).exists():
            df = pd.read_csv(CSV_PATH, on_bad_lines='skip')
            if "id" not in df: raise ValueError("Catalog CSV must have an 'id' column.")
            df["id"] = df["id"].astype(str)
            for col in FILTER_COLUMNS:
                df[col] = df[col].astype(str).str.lower().str.strip() if col in df else ""
            df["price"] = pd.to_numeric(df.get("price_inr"), errors='coerce')
            df.dropna(subset=['price', 'id'], inplace=True)
            df['price'] = df['price'].astype(float)
            _catalog = df
            _catalog_stats = {col: [item for item in _catalog[col].unique() if item] for col in FILTER_COLUMNS if col in _catalog}
            _filter_patterns = compile_patterns(_catalog_stats)
        else: raise RuntimeError(f"Catalog CSV not found at {CSV_PATH}.")

def compile_patterns(stats: Dict[str, List[str]]) -> Dict[str, re.Pattern]:
    """Compile regex patterns from catalog stats for efficient fallback parsing."""
    patterns = {}
    for col, values in stats.items():
        if values:
            sorted_values = sorted(values, key=len, reverse=True)
            escaped_values = [re.escape(v) for v in sorted_values if v]
            if escaped_values:
                patterns[col] = re.compile(r'\b(' + '|'.join(escaped_values) + r')\b', re.IGNORECASE)
    return patterns

def extract_filters_fallback(query_text: str, patterns: Dict[str, re.Pattern]) -> Dict:
    """A regex-based parser to be used when the Gemini API fails."""
    query = (query_text or "").lower()
    filters = {k: None for k in FILTER_COLUMNS + ["priceMin", "priceMax"]}
    if patterns:
        for k, pattern in patterns.items():
            if pattern:
                match = pattern.search(query)
                if match: filters[k] = match.group(0).lower()
    price_max_match = re.search(r'\b(?:under|below|less than|max)\s*(\d+)\b', query)
    if price_max_match: filters['priceMax'] = int(price_max_match.group(1))
    price_min_match = re.search(r'\b(?:above|over|more than|min)\s*(\d+)\b', query)
    if price_min_match: filters["priceMin"] = int(price_min_match.group(1))
    between_match = re.search(r'\bbetween\s*(\d+)\s*(?:and|to)\s*(\d+)\b', query)
    if between_match:
        prices = sorted([int(between_match.group(1)), int(between_match.group(2))])
        filters['priceMin'], filters["priceMax"] = prices[0], prices[1]
    return {"filters": filters, "normalized_query": query.strip(), "strict": False}

def encoded_text_cpu(text: str) -> np.ndarray:
    if _model is None or _tokenizer is None: data_load()
    tokens = _tokenizer([text])
    with torch.no_grad():
        feats = _model.encode_text(tokens.to(DEVICE))
        feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats.cpu().numpy().astype("float32")

def encoded_text_cpu_batch(texts: List[str]) -> np.ndarray:
    """Encodes a batch of text strings efficiently."""
    if _model is None or _tokenizer is None: data_load()
    if not texts: return np.array([]).astype("float32")
        
    tokens = _tokenizer(texts).to(DEVICE)
    with torch.no_grad():
        feats = _model.encode_text(tokens)
        feats /= feats.norm(dim=-1, keepdim=True)
    return feats.cpu().numpy().astype("float32")


def apply_filters(df: pd.DataFrame, filters: Dict) -> pd.DataFrame:
    """Applies a dictionary of filters to a DataFrame strictly."""
    filtered_df = df.copy()
    
    price_min = filters.get("priceMin")
    price_max = filters.get("priceMax")
    if price_min is not None:
        try: filtered_df = filtered_df[filtered_df['price'] >= float(price_min)]
        except (ValueError, TypeError): pass
    if price_max is not None:
        try: filtered_df = filtered_df[filtered_df['price'] <= float(price_max)]
        except (ValueError, TypeError): pass
        
    active_filters = {col: val for col, val in filters.items() if col in FILTER_COLUMNS and val and val != 'unisex'}
    if not active_filters: return filtered_df
        
    final_mask = pd.Series([True] * len(filtered_df), index=filtered_df.index, dtype=bool)
    for col, val in active_filters.items():
        if col in filtered_df.columns: final_mask &= (filtered_df[col] == val)
            
    return filtered_df[final_mask]

def build_product_dict(row: pd.Series, query: str, filters: Dict, note: str) -> Dict:
    return {
        "id": str(row["id"]), "name": str(row.get("productDisplayName") or ""),
        "masterCategory": str(row.get("masterCategory") or ""), "subCategory": str(row.get("subCategory") or ""),
        "articleType": str(row.get("articleType") or ""), "gender": str(row.get("gender") or ""),
        "color": str(row.get("baseColour") or ""),
        "price": float(row["price"]) if pd.notna(row["price"]) else None,
        "image": "",
        "similarity": float(row.get("similarity", 0)),
        "rationale": {"query": query, "filters": filters, "note": note}
    }

def search_primary_and_recommendations(
    query_text: str,
    num_recommendations: int = 5,
    parsed_intent:tuple=None
) -> Tuple[Optional[Dict], List[Dict]]:
    data_load()
    _top_k_faiss_search = 100
    

    parsed_intent, error = parsed_intent
    if error:
        print(f"Warning: Gemini parser failed: '{error}'. Falling back to regex parser.")
        parsed_intent = extract_filters_fallback(query_text, _filter_patterns)
  

    raw_filters = parsed_intent.get("filters", {})
    filters = {
        key: value.lower() if isinstance(value, str) else value
        for key, value in raw_filters.items()
    }
    normalized_query = parsed_intent.get("normalized_query", query_text)

    qvec = encoded_text_cpu(normalized_query)
    scores, idx = _index.search(qvec, _top_k_faiss_search)
    scores, idx = scores[0], idx[0]

    valid_indices = idx >= 0
    if not np.any(valid_indices): return None, []
    ids = _idmap[idx[valid_indices]]
    scores = scores[valid_indices]

    hits = pd.DataFrame({"id": ids, "_score": scores})
    hits = hits.merge(_catalog, on="id", how="inner")
    if hits.empty: return None, []

    hits = hits.sort_values("_score", ascending=False).drop_duplicates("id")
    hits = hits.assign(similarity=(hits["_score"] * 100.0).round(2))

   
    strict_hits = apply_filters(hits, filters)
    if not strict_hits.empty:
        primary_row = strict_hits.iloc[0]
        primary = build_product_dict(primary_row, query_text, filters, "primary from strict filter matches")
        recos_df = strict_hits[strict_hits['id'] != primary['id']].head(num_recommendations)
        recos = [build_product_dict(r, query_text, filters, "similar strict match") for _, r in recos_df.iterrows()]
        return primary, recos

    
    filters_no_price = {k: v for k, v in filters.items() if k not in ["priceMin", "priceMax"]}
    if filters_no_price != filters:
        price_relaxed_hits = apply_filters(hits, filters_no_price)
        if not price_relaxed_hits.empty:
            recos = [build_product_dict(r, query_text, filters, "fallback: price relaxed") for _, r in price_relaxed_hits.head(num_recommendations).iterrows()]
            return None, recos

    
    filters_no_price_color = {k: v for k, v in filters_no_price.items() if k != "baseColour"}
    if filters_no_price_color != filters_no_price:
        core_hits = apply_filters(hits, filters_no_price_color)
        if not core_hits.empty:
            recos = [build_product_dict(r, query_text, filters, "fallback: price and color relaxed") for _, r in core_hits.head(num_recommendations).iterrows()]
            return None, recos
        
    
    recos = [build_product_dict(r, query_text, filters, "semantic fallback") for _, r in hits.head(num_recommendations).iterrows()]
    return None, recos
def search_batch_and_find_primary(
    parsed_intents: List[Dict]
) -> List[Optional[Dict]]:
    """
    Performs a batch search for multiple queries at once for high efficiency.
    For each query, it finds the single best primary match from the catalog.
    """
    data_load() # Ensure all resources are loaded
    
    if not parsed_intents:
        return []
    
    # Extract normalized queries for batch embedding
    query_texts = [intent.get("normalized_query", "") for intent in parsed_intents]
    
    # 1. Create a batch of embeddings in one go
    embeddings = encoded_text_cpu_batch(query_texts)
    
    # 2. Perform a single, powerful FAISS search for all queries at once
    # k=100 means we get the top 100 candidates for EACH of the queries
    _top_k_faiss_search = 100
    batch_scores, batch_idx = _index.search(embeddings, _top_k_faiss_search)
    
    results = []
    # 3. Process the results for each query in the batch
    for i in range(len(query_texts)):
        intent = parsed_intents[i]
        filters = intent.get("filters", {})
        
        # Get the candidates for this specific query
        ids = _idmap[batch_idx[i]]
        scores = batch_scores[i]
        
        # Merge with catalog to get full product details
        hits = pd.DataFrame({"id": ids, "_score": scores})
        hits = hits.merge(_catalog, on="id", how="inner")
        
        if hits.empty:
            results.append(None)
            continue
        
        # Apply the specific filters for this query using the existing function
        filtered_hits = apply_filters(hits, filters)
        
        # Fallback to unfiltered semantic hits if filters yield no results
        final_hits = filtered_hits if not filtered_hits.empty else hits
        
        if final_hits.empty:
            results.append(None) # No match found for this query
            continue
            
        # Get the single best match after sorting and removing duplicates
        best_hit = final_hits.sort_values("_score", ascending=False).drop_duplicates("id").iloc[0]
        results.append(best_hit.to_dict())
        
    return results