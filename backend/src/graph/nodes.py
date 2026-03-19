import json 
import os
import logging
import re
from typing import Dict, Any
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_community.vectorstores import AzureSearch
from langchain_core.messages import SystemMessage, HumanMessage

# import state schema
from backend.src.graph.state import VideoAuditState

# import service
from backend.src.services.video_indexer import VideoIndexerService

# config the logger
logger = logging.getLogger("brand-guardian")
logging.basicConfig(level=logging.INFO)

# NODE 1 : Indexer
# function responsible for converting video to text
def index_video_node(state : VideoAuditState) -> Dict[str, Any]:
    '''Download the youtube video from the url
       Uploads to the Azure Video Indexer
       extracts the insights
      '''
    
    video_url = state.get("video_url")
    video_id_input = state.get("video_id", "vid_demo")

    logger.info(f"------[Node:Indexer] Processing : {video_url}")

    local_filename = "temp_audit_video.mp4"

    try:
        vi_service = VideoIndexerService()
        # download : yt-dlp
        if "youtube.com" in video_url or "youtu.be" in video_url:
            local_path = vi_service.download_youtube_video(video_url, output_path = local_filename)
        else:
            raise Exception("Please provide a valid Youtube URL for this test.")

        # upload
        azure_video_id = vi_service.upload_video(local_path, video_name = video_id_input)
        logger.info(f"Upload Success. Azure ID : {azure_video_id}")
        # cleanup
        if os.path.exists(local_path):
            os.remove(local_path)
        
        # wait 
        raw_insights = vi_service.wait_for_processing(azure_video_id)
        # extract
        clean_data  = vi_service.extract_data(raw_insights)
        clean_data["video_id"] = video_id_input
        logger.info("---[NODE: Indexer] Extraction Complete ----------")
        return clean_data
    
    except Exception as e:
        logger.error(f"Video Indexer Failed : {e}")
        return {
            "video_id": video_id_input,
            "errors" : [str(e)],
            "final_status" : "FAIL",
            "final_report": "Audit skipped because video indexing failed.",
            "transcript" : "",
            "ocr_text" : []
        }
    
# Node 2 : Compliance Auditor
def audit_content_node(state:VideoAuditState) -> Dict[str, Any]:
    '''
    Performs Retrieval Augmented Generation to audit the content -  brand video
    '''
    logger.info("----[Node : Auditor] querying Knowledge basse & LLM")
    transcript = state.get("transcript", "")
    if not transcript:
        logger.warning("No transcript available. Skipping audit.....")
        return{
            "video_id": state.get("video_id", "vid_demo"),
            "final_status" : "FAIL",
            "final_report" : "Audit Skipped because video processing failed (No Transcript.)"
        }
    
    # initialize azure clients
    llm = AzureChatOpenAI(
        azure_deployment= os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        api_version = os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key = os.getenv("AZURE_OPENAI_API_KEY"),
        temperature = 0.0
    )

    embeddings = AzureOpenAIEmbeddings(
        azure_deployment=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        api_version = os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key = os.getenv("AZURE_OPENAI_API_KEY"),
    )

    vector_store = AzureSearch(
        azure_search_endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
        azure_search_key= os.getenv("AZURE_SEARCH_API_KEY"),
        index_name = os.getenv("AZURE_SEARCH_INDEX_NAME"),
        embedding_function= embeddings.embed_query
    )

    # RAG REtrieval
    ocr_text = state.get("ocr_text", [])
    query_text = f"{transcript} {''.join(ocr_text)}"
    docs = vector_store.similarity_search(query_text, k=3)
    retrieved_rules = '\n\n'.join([doc.page_content for doc in docs])

    # 
    system_prompt = f"""
        You are a Senior Brand Compliance Auditor.
        
        OFFICIAL REGULATORY RULES:
        {retrieved_rules}
        
        INSTRUCTIONS:
        1. Analyze the Transcript and OCR text below.
        2. Identify ANY violations of the rules.
        3. Return strictly JSON in the following format:
        
        {{
            "compliance_results": [
                {{
                    "category": "Claim Validation",
                    "severity": "CRITICAL",
                    "description": "Explanation of the violation..."
                }}
            ],
            "status": "FAIL", 
            "final_report": "Summary of findings..."
        }}

        If no violations are found, set "status" to "PASS" and "compliance_results" to [].
        """
    user_message = f"""
                    VIDEO_METADATA : {state.get('video_metadata', {})}
                    TRANSCRIPT : {transcript}
                    ON_SCREEN TEXT (OCR) : {ocr_text}
                    """

    try:
        response = llm.invoke([
            SystemMessage(content = system_prompt),
            HumanMessage(content = user_message)
        ])
        content = response.content
        if "```" in content:
            match = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
            if match:
                content = match.group(1)
        audit_data = json.loads(content.strip())
        return {
            "video_id": state.get("video_id", "vid_demo"),
            "compliance_results" : audit_data.get("compliance_results", []),
            "final_status" : audit_data.get("status", "FAIL"),
            "final_report" : audit_data.get("final_report", "No report generated")
        }
    
    except Exception as e:
        logger.error(f"System Error in Auditor Node : {str(e)}")
        # logging the raw response
        logger.error(f"Raw LLM response : {response.content if 'response' in locals() else 'None'}")
        return {
            "video_id": state.get("video_id", "vid_demo"),
            "errors" : [str(e)],
            "final_status" : "FAIL",
            "final_report": "Audit failed in the compliance auditor step."
        }
