"""
LumenAI + LangChain - automatic cost tracking for every LLM call.

Prerequisites:
    pip install lumen-ai-core lumen-ai-openlit openlit langchain-openai

Usage:
    export OPENAI_API_KEY=<your-key>
    python main.py
"""
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from lumen_ai import LumenAI, lumen_tenant
from lumen_ai_openlit import OpenLITBridge

# 1. Initialize LumenAI and activate provider instrumentation once at startup.
LumenAI.init(
    service_name="langchain-app",
    default_tenant="my-company",
    redis_url="redis://localhost:6379/0",
    instrumentors=[OpenLITBridge()],
)

# 2. Use LangChain as usual; LumenAI tracks cost automatically
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# 3. Tenant context propagates through the entire chain
with lumen_tenant("client-acme"):
    response = llm.invoke([HumanMessage(content="What is FinOps?")])
    print(response.content)

# 4. Different tenant, same code
with lumen_tenant("client-globex"):
    response = llm.invoke([HumanMessage(content="Explain observability in 2 sentences.")])
    print(response.content)

# Cost per tenant is now in Redis:
#   XRANGE LumenAI:events:client-acme - +
#   XRANGE LumenAI:events:client-globex - +

LumenAI.shutdown()
