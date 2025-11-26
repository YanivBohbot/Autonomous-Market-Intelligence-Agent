from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from app.core.config import settings
from app.agent.state import AgentState


class GradeDocument(BaseModel):
    binary_score: str = Field(description="'yes' or 'no'")


def grade_documents(state: AgentState):
    print("⚖️ [NODE] GRADER: Notation...")
    question = state["question"]
    documents = state["documents"]

    llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
    structured_llm_grader = llm.with_structured_output(GradeDocument)

    system_prompt = " the document answer to the question ? answer 'yes' ou 'no'."

    filtered_docs = []

    for doc in documents:
        res = structured_llm_grader.invoke(
            f"Question: {question}\nDoc: {doc}\n{system_prompt}"
        )
        if res.binary_score == "yes":
            filtered_docs.append(doc)

    return {"documents": filtered_docs}
