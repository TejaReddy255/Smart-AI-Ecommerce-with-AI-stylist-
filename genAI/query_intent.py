from typing import Dict,Any,Optional,Tuple,List
from google import genai
from google.genai import types
from google.api_core.exceptions import GoogleAPICallError,ResourceExhausted
import json
import os
from dotenv import load_dotenv
import pandas as pd
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
from config import settings


API_KEY=settings.GENAI_API_KEY

response_schema ={
   "type":"OBJECT",
   "properties":{
      "filters":{
         "type":"OBJECT",
         "properties":{
            "gender":{"type":"STRING"},
            "masterCategory":{"type":"STRING"},
            "subCategory":{"type":"STRING"},
            "articleType":{"type":"STRING"},
            "baseColour":{"type":"STRING"},
            "priceMax":{"type":"INTEGER","nullable":True},
            "priceMin":{"type":"INTEGER","nullable":True}
         },
         "required":['gender','masterCategory','subCategory','articleType','baseColour']
      },
      "normalized_query":{"type":"STRING"},
      "strict":{'type':'Boolean'},
   },
    "required":["filters","normalized_query","strict"]
}
ALLOWED_FIELDS =[
   "gender","masterCategory","subCategory","articleType","baseColour","priceMax", "priceMin"
]

PROMPT_TEMPLATE="""
You are an expert e-commerce intent parser.

Your task:extract product filters from the user query and normalize them strictly to the allowed values.you should strictly follow below instructions

Allowed Values:
{allowed_values}

Instructions:
1. Extract the following fields from the query:'gender','masterCategory','subCategory','articleType','baseColour'.

2. Normalize all extracted values to the closest allowed Values from the catalog 
     -If a values is not in the allowed values,set it to null
     
3. If a word like 'women','men', or 'kids' appears, set 'gender' to that value.if no clear gender is mentioned use 'Unisex'.

4. If price is mentioned:
      -For e.g "under 1000", "below 500" -> set priceMax = that number.
      -For e.g"above 1000", "over 500" -> set priceMin = that number.
      -For e.g  "between 500 and 1000" , "between 500 to 1000" -> set priceMin = 500 and priceMax= 1000, always set maximum value in priceMax and minimum value in priceMin. 

5. set "strict" to true **only if all values explicitly mentioned in the query match exactly to allowed catalog valus**.
   - Do not set strict false for fields that the user did not mention(they can remin null)
   - set strict false if any value is normalized inferred or approximated.  

6. Return only raw JSON without any strings,qutation,markdowns and ticks and it raw json should contain exactly these Key:
      - filters(object)  must inclue gender,masterCategory,subCategory,articleType,baseColour 
      - normalized_query(string) : normalized version of the user query
      - strict(boolean) : True or False

output format:
{{
   "filters": {{
   "gender":"<value or null>",
    "masterCategory":"<value or null>",
    "subCategory":"<value or null>",
    "articleType":"<value or null>",
    "baseColour":"<value or null>",
    "priceMax":<number or null>",
    "priceMin:<number or null>"}},
  "normalized_query":"<normalized user quer>",
  "strict":"<set True or False based on instruction>"
}}

Query:{query}
"""
BATCH_PROMPT_TEMPLATE = """
You are an expert e-commerce intent parser. Your task is to extract product filters from a list of user queries and normalize them strictly to the allowed values. For each query in the input list, generate a corresponding JSON object.

Allowed Values:
{allowed_values}

Instructions for EACH query:
1.  Extract filters: 'gender', 'masterCategory', 'subCategory', 'articleType', 'baseColour'.
2.  Normalize all extracted values to the closest allowed value. If a value is not in the list, set it to null.
3.  Handle gender and price as instructed.
4.  Set "strict" to true ONLY if all values in a query match exactly.
5.  Your final output must be a single JSON array containing one object for each query you processed.

Input Queries:
{queries_json_list}
"""

def _format_allowed_values(catalog_stats:Dict[str,List[str]]) -> str:
   """
   convert catalog_stats dict into readable bullet-sty;e string for prompt
   """    
   return "\n".join(
      f"- {field}: {values}" for field,values in catalog_stats.items()
   )

def _validate_field(field:str, value: Any, catalog_stats:Dict[str,list]) ->Any:
   """
   validate and normalize a field against allowed catalog values.
   """
   if value is None:
      return None
   if field  == "priceMax":
      return value if isinstance(value,(int,float)) else None
   
   if field  == "priceMin":
      return value if isinstance(value,(int,float)) else None
   
   allowed =catalog_stats.get(field,[])
   
   return value if isinstance(value,str) and value in allowed else None


def build_prompt(query:str,catalog_stats:Dict[str,List[str]]) ->str:
   """
   Builds a structured prompt for Gemini with strict disambiguation rules.
   """

   allowed_values_str = _format_allowed_values(catalog_stats)
   return PROMPT_TEMPLATE.format(
      allowed_values = allowed_values_str,
      query = query
   )

def parse_intent_with_gemini(query:str,catalog_stats:Dict[str,list]):
   """
   Parses a raw search query into structured intent using Gemini
   """
   try:
      if API_KEY:
         client = genai.Client(api_key=API_KEY)

      prompt =build_prompt(query,catalog_stats)
      
      
      response =client.models.generate_content(
                     model="gemini-1.5-flash",
                     contents=prompt,
                     config=types.GenerateContentConfig(response_mime_type='application/json',response_schema=response_schema)
                     )
      
      #print(response.text)
      if not response or not hasattr(response,"text") or not response.text:
         return {
                  "filters":{field:None for field in ALLOWED_FIELDS},
                  "normalized_query":query,
                  "strict":False
                }
      parsed =json.loads(response.text)
      
      raw_filters = parsed.get('filters',{})
      cleaned_filters ={
         field:_validate_field(field,raw_filters.get(field),catalog_stats)
         for field in ALLOWED_FIELDS
      }
      
      parsed_intent ={
         "filters":cleaned_filters,
         "normalized_query":str(parsed.get("normalized_query",query)),
         "strict":bool(parsed.get("strict",True))
      }

      return parsed_intent,None
   except ResourceExhausted:
      return {},"Gemini free-tier quota exceeded. Please try later"
   except GoogleAPICallError as api_error:
      return {}, f"Gemini API error:{api_error}"
   except json.JSONDecodeError as decode_error:
      return {},f"Invalid JSON from model:{decode_error}"
   except Exception as general_error:
      return {} ,f"Error parsing intent:{general_error}"
def parse_intent_batch_with_gemini(queries: List[str], catalog_stats: Dict[str, List[str]]) -> Tuple[List[Dict], Optional[str]]:
    """
    Parses a BATCH of search queries into structured intents in a single API call.
    """
    if not queries:
        return [], None
        
    try:
        client = genai.Client(api_key=API_KEY)
        # The schema for the response is now an ARRAY of the original object schema
        batch_response_schema = {"type": "ARRAY", "items": response_schema}
        
       
        
        prompt = BATCH_PROMPT_TEMPLATE.format(
            allowed_values=_format_allowed_values(catalog_stats),
            queries_json_list=json.dumps(queries)
        )
        
        response =client.models.generate_content(
                     model="gemini-1.5-flash",
                     contents=prompt,
                     config=types.GenerateContentConfig(response_mime_type='application/json',response_schema=batch_response_schema)
                     )
        
        if not response.text:
            return [], "Model returned an empty response for the batch."

        parsed_list = json.loads(response.text)
        
        # Post-validation of each parsed item
        validated_intents = []
        for parsed in parsed_list:
            raw_filters = parsed.get('filters', {})
            # You can add the _validate_field logic here if needed for extra safety
            validated_intents.append({
                "filters": raw_filters,
                "normalized_query": str(parsed.get("normalized_query", "")),
                "strict": bool(parsed.get("strict", False))
            })
            
        return validated_intents, None

    except Exception as e:
        return [], f"Error parsing batch intent with Gemini: {e}"


if __name__=="__main__":
   catalog_df = pd.read_csv("data/styles.csv")
   stats = {}
   for col in ['gender','masterCategory','subCategory','articleType','baseColour']:
      stats[col]= catalog_df[col].dropna().unique().tolist() if col in catalog_df else []

   query = "Shirt"
   parsed_intent= parse_intent_with_gemini(query,stats)
   print(parsed_intent)

