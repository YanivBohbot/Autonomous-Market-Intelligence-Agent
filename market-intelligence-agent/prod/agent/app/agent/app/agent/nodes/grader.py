import logging
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from app.core.config import settings
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


class GradeDocument(BaseModel):
    binary_score: str = Field(description="'yes' or 'no'")


_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
_grader = _llm.with_structured_output(GradeDocument)


def grade_documents(state: AgentState) -> dict:
    logger.info("GRADER: Scoring %d documents", len(state["documents"]))
    question = state["question"]
    documents = state["documents"]
    system_prompt = "Does the document answer the question? Answer 'yes' or 'no'."
    filtered_docs = []
    for doc in documents:
        res = _grader.invoke(f"Question: {question}\nDoc: {doc}\n{system_prompt}")
        if res.binary_score == "yes":
            filtered_docs.append(doc)
    logger.info("GRADER: Kept %d/%d documents", len(filtered_docs), len(documents))
    return {"documents": filtered_docs}
