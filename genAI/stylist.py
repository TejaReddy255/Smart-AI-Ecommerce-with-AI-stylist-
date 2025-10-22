
import json
from typing import Dict, List, Any
import pandas as pd
import sys,os
import streamlit as st
import google.generativeai as genai
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
# Import from our custom search engine module
from train_model.search_engine import search_batch_and_find_primary
from genAI.query_intent import parse_intent_batch_with_gemini
from config import settings
import json
from typing import Dict, List, Any, Optional
import pandas as pd
import google.generativeai as genai
# FILE: stylist.py




API_KEY = settings.GENAI_API_KEY

# --- AI Stylist ("Shop the Look") Logic ---

# Prompt for Stage 1: Generate creative, human-like queries
CREATIVE_STYLE_PROMPT_TEMPLATE = """
You are an AI-powered virtual stylist. A customer is viewing the following product:
---
- Product Name: {product_name}
- Master Category: {master_category}
- Gender: {gender}
---
Here is a sample of available complementary item *types* from our catalog: {styles_data_json}
---
Your task is to suggest a **complete 5-item outfit**. Recommend creative, human-like search queries covering different categories like bottomwear, footwear, and accessories.

Respond **ONLY** with a JSON array of 5 simple strings.
"""

def get_complementary_catalog_sample(anchor_product: Dict[str, Any], catalog_df: pd.DataFrame, sample_size: int = 60) -> List[Dict[str, Any]]:
    """Selects a relevant, random sample from the catalog to ground the LLM's suggestions."""
    COMPLEMENTARY_MAP = {
        "accessories": ["apparel", "footwear", "bottomwear"], "apparel": ["footwear", "accessories", "bottomwear"],
        "footwear": ["apparel", "accessories", "bottomwear"], "personal care": ["apparel", "accessories"],
        "dress": ["footwear", "accessories"], "bottomwear": ["apparel", "footwear", "accessories"]
    }
    anchor_category = anchor_product.get("masterCategory", "").lower()
    anchor_gender = anchor_product.get("gender", "").lower()
    target_categories = COMPLEMENTARY_MAP.get(anchor_category, list(COMPLEMENTARY_MAP.keys()))
    
    complementary_df = catalog_df[(catalog_df['masterCategory'].str.lower().isin(target_categories)) & (catalog_df['gender'].str.lower() == anchor_gender)]
    if complementary_df.empty: return []
    
    actual_sample_size = min(sample_size, len(complementary_df))
    return complementary_df.sample(n=actual_sample_size)[['articleType', 'baseColour']].to_dict('records')

def query_stylist_for_creative_ideas(product: Dict[str, Any], styles_data: List[Dict[str, Any]]) -> List[str]:
    """STAGE 1: Queries the Gemini LLM to get a list of creative search query ideas."""
    try:
        genai.configure(api_key=API_KEY)
        gemini_model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        
        prompt = CREATIVE_STYLE_PROMPT_TEMPLATE.format(
            product_name=product.get('productDisplayName'), master_category=product.get('masterCategory'),
            gender=product.get('gender'), styles_data_json=json.dumps(styles_data, indent=2)
        )
        response = gemini_model.generate_content(prompt)
        
        raw_text = response.text.strip()
        json_start = raw_text.find('[')
        json_end = raw_text.rfind(']') + 1
        if json_start == -1 or json_end == 0: return []
        
        ideas = json.loads(raw_text[json_start:json_end])
        return ideas if isinstance(ideas, list) else []
    except Exception as e:
        print(f"[ERROR] AI Stylist creative idea generation failed: {e}")
        return []

def find_matching_catalog_items_with_parser(
    creative_queries: List[str], 
    parsed_intents: List[Dict],
    anchor_product: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Takes creative queries and their parsed intents, finds matching products using a BATCH search."""
    used_ids = {str(anchor_product.get("id"))}
    
    # Call the batch search function with all queries and parsed intents at once
    batch_results = search_batch_and_find_primary(parsed_intents=parsed_intents)

    matched_items = []
    # Process the results from the batch search
    for i, primary_match in enumerate(batch_results):
        if primary_match and str(primary_match.get("id")) not in used_ids:
            primary_match['rationale'] = {
                "note": "AI Stylist Recommendation", 
                "creative_query": creative_queries[i]
            }
            matched_items.append(primary_match)
            used_ids.add(str(primary_match.get("id")))
        else:
            print(f"[Stylist] -> No unique product found for idea: '{creative_queries[i]}'")

    return matched_items

def generate_stylist_outfit(
    anchor_product: Dict[str, Any], 
    catalog_df: pd.DataFrame, 
    catalog_stats: Dict[str, List[str]], 
) -> List[Dict[str, Any]]:
    """Main orchestrator for the FASTER, BATCHED, two-stage AI Stylist."""
    # STAGE 1: Get 5 creative ideas in one LLM call
    complementary_sample = get_complementary_catalog_sample(anchor_product, catalog_df)
    creative_ideas = query_stylist_for_creative_ideas(anchor_product, complementary_sample)
    if not creative_ideas: 
        print("[INFO] AI Stylist returned no creative ideas.")
        return []
    print(f"\n[INFO] AI Stylist creative ideas: {json.dumps(creative_ideas, indent=2)}")
    
    # STAGE 2: Parse all 5 ideas in a single BATCH LLM call
    print("\n[INFO] Parsing all creative ideas in a single batch call...")
    parsed_intents, error = parse_intent_batch_with_gemini(creative_ideas, catalog_stats)
    if error:
        print(f"[ERROR] Batch intent parsing failed: {error}")
        return []
    print("[INFO] Batch parsing successful.")

    # Use the parsed intents to find real products via batch search
    return find_matching_catalog_items_with_parser(creative_ideas, parsed_intents, anchor_product)

# # --- Main Test Function (using mocks) ---

# def main():
#     """Entry point for testing the faster stylist script."""
#     print("--- Testing Faster, Controlled AI Stylist ---")
    
#     # Mock settings and catalog for a standalone test

  

#     # Define an example anchor product from your styles.csv
#     anchor_product = {
#         "id": "26057",
#         "productDisplayName": "John Miller Men Check Purple Shirt",
#         "masterCategory": "apparel",
#         "articleType": "shirts",
#         "baseColour": "purple",
#         "gender": "men",
#         "price": 1590.0
#     }
#     print(f"\n[INFO] Anchor Product: {anchor_product['productDisplayName']}")

#     # Call the main function to get outfit recommendations
#     outfit_recommendations = generate_stylist_outfit(anchor_product, CATALOG_DF)

#     # Print the final results
#     if outfit_recommendations:
#         print("\n--- ✅ Final Recommended Outfit Products (from styles.csv) ---")
#         for item in outfit_recommendations:
#             print(json.dumps(item, indent=2))
#     else:
#         print("\n--- ❌ No outfit recommendations could be generated. ---")

# if __name__ == "__main__":
#     main()