import operator 
from typing import Annotated, List, Dict, Optional, Any, TypedDict

# define the schema for a single compliance result

class ComplianceIssue(TypedDict):
    category : str
    description : str # specific details of violation
    severity : str # CRITICAL details of voliation
    timestamp : Optional[str]

# this define the state that gets passed around in the agentic workflow
class VideoAuditState(TypedDict):
    '''
    Defines the data schema for langgraph execution content
    Main container :  holds all the information about the audit
    right from the initial URL to the final report
    '''
    # input parameters
    video_url : str
    video_id : str

    # ingestion and extraction data
    local_file_path : Optional[str]
    video_metadata : Dict[str, Any] # {"duration" : 15, "resolution" : "1080p"}
    transcript : Optional[str] # Fully extracted speech-to-text
    ocr_text : List[str]

    # analysis output
    # stores the list of all the voilations found by AI
    compliance_results : Annotated[List[ComplianceIssue], operator.add]

    # final deliverables: 
    final_status : str # PASS | FAIL
    final_report : str # markdown format

    # system obervability 
    # errors : API timeout, system level errors
    # list of system level crashes
    errors : Annotated[List[str], operator.add]
