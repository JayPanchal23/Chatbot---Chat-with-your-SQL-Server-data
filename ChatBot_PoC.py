from langchain.memory import ConversationBufferMemory,ConversationBufferWindowMemory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain.agents import AgentType, AgentExecutor
from langchain_core.messages import SystemMessage
from langchain_core.prompts import MessagesPlaceholder, HumanMessagePromptTemplate
from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain.prompts.chat import ChatPromptTemplate
from sqlalchemy import create_engine, MetaData, select
from logtail import LogtailHandler
import logging, os
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from langchain_community.callbacks import get_openai_callback


# Set up Azure Key Vault client
credential = DefaultAzureCredential()
key_vault_url = "https://domain.vault.azure.net/"
secret_client = SecretClient(vault_url=key_vault_url, credential=credential)

# # Fetch secrets from Key Vault
# openai_api_key = secret_client.get_secret("OPENAI-API-KEY").value
# db_connection_string = secret_client.get_secret("DB-CONNECTION-STRING").value
# logger_token = secret_client.get_secret("LOGGER-TOKEN").value

openai_api_key = "<OPENAI-KEY>"
db_connection_string = "mssql+pyodbc://USER:PASSWORD@SERVER/DB?driver=ODBC+Driver+17+for+SQL+Server"
logger_token = "LOGGER_TOKEN"


# Set OpenAI API key in environment variable
os.environ["OPENAI_API_KEY"] = openai_api_key

# Set logger
handler = LogtailHandler(source_token=logger_token)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.handlers = []
logger.addHandler(handler)

logger.info('Imported ChatBot packages')


# Connect with Read-Only Database
logger.info('Connecting with database')
engine = create_engine(db_connection_string, pool_size=10, max_overflow=20)
database = SQLDatabase(engine)
logger.info('Connected with database!')


# Get configuration details from database
logger.info('Fetching configuration details for chatbot..')
config_conn = engine.connect()
meta = MetaData()
meta.reflect(bind=engine)
config_table = meta.tables['chatbot_config']
config_details = select(config_table).where(config_table.c["version"] == '2.1.1')
config_details = config_conn.execute(config_details).fetchone()

chatbot_model = config_details[1]
model_temperature = int(config_details[2])
model_max_tokens = config_details[3]
model_timeout = config_details[4]
model_max_retries = config_details[5]
prompt_text = config_details[6]
agent_max_execution_time = config_details[7]
agent_max_iteration = config_details[8]
agent_top_k = config_details[9]
jwt_token_expiration = config_details[10]
jwt_algorithm = config_details[11]
logger.info('Fetched configuration details for chatbot.')


# Prepare LLM and toolkit
llm = ChatOpenAI(model=chatbot_model,
                 temperature=model_temperature,
                 max_tokens=model_max_tokens,
                 timeout=model_timeout,
                 max_retries=model_max_retries,
                 # memory=memory
                 )

toolkit = SQLDatabaseToolkit(db=database, llm=llm)
tools = toolkit.get_tools()
logger.info('Prepared SQL database toolkit')


# Prepare prompt and agent
prompt = ChatPromptTemplate.from_messages(
                                            [
                                                ("system","""Always use where condition [Hour] = (SELECT MAX([Hour]) FROM stock_hourly_day WHERE [Date] = '<user specified date>>') in stock_hourly_day table and fetch latest stock details for specified date. While fetching product wise stock availability, ensure that the "Stock Qty Singles" column in the stock_hourly_day table is not summed. Brand can be fetched from product_further_detail table using LIKE. Never join on [Unique Transaction Id] = [Product Id]. use transaction_grouped_view_2y table to fetch product wise selling using Total Value column. you are a very intelligent AI assistant who is expert in identifying relevant question from user and converting into sql queries to generate correct answer. Write the microsoft sql queries, do not use mysql queries. As an expert you must use joins whenever required. Whenever question regarding product is asked for particular department, you must identify correct product by mapping Department column of departments table with Prod Hierarchy 1 column of product table.There are multiple payment modes and along with transaction details in transaction_qt table. transaction_qt is the Most relevant table for fetching transaction with payment mode. Get Brand from product_further_detail table. Profit can be calculated as SUM([Total Value] + [Total Bonus Due] - [Cost]). Use only transaction_grouped_view_2y table for Quantity sold cases and calculated as [Qty Sold Cases] = [Qty Sold Singles]/[Unit Of Purchase]. Use Target table only when asked to answer sales and target or sales against target or sales-target, use this SQL query structure SELECT t.[Depot Id], SUM(t.[Target]) AS Total_Target, s.Total_Sales FROM target t JOIN (SELECT [Depot Id], SUM([Total Value]) AS Total_Sales FROM transaction_grouped_view_2y WHERE [Date] = '<user provided date>' GROUP BY [Depot Id]) s ON t.[Depot Id] = s.[Depot Id] WHERE t.[Date] = '<user provided date>' GROUP BY t.[Depot Id], s.Total_Sales."""),
                                                 # Depot wise stock availability can be fetched by summing stock qty singles, filtering by latest hour and for specified date
                                                # MessagesPlaceholder("history"),
                                                ("user", "{question}")
                                            ]
                                         )

# memory = ChatMessageHistory(session_id="test-session")
memory = ConversationBufferWindowMemory(k=1)

agent = create_sql_agent(llm=llm,toolkit=toolkit, agent_type=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
                         max_execution_time=agent_max_execution_time, max_iterations=agent_max_iteration, verbose=True,
                         top_k=agent_top_k, agent_executor_kwargs={'handle_parsing_errors': True}, memory=memory)


agent_with_chat_history = RunnableWithMessageHistory(
                                agent,
                                # This is needed because in most real world scenarios, a session id is needed
                                # It isn't really used here because we are using a simple in memory ChatMessageHistory
                                lambda session_id: memory,
                                input_messages_key="input",
                                history_messages_key="chat_history",)

agent_with_chat_history.invoke({"input": "how much % mobie payment made by that customer?"},
    config={"configurable": {"session_id": "<bar>"}},)


agent.return_intermediate_steps = True
logger.info('Created sql agent')
with get_openai_callback() as cb:
    result = agent(prompt.format_prompt(question="customer 500 details"))
    logger.info('Testing Prompt | ' + str(result['input'].to_messages()[1].content) + " | " + str(result['output']) + " | " +
                str(result['intermediate_steps']) + " | " + str(cb.total_tokens) + " | " + str(cb.total_cost))
# result = agent(prompt.format_prompt(question="Please share the details of customer ID 500"))


def reconnect_db():
    logger.info('Reconnecting with database')
    global engine,database
    engine = create_engine(db_connection_string, pool_size=10, max_overflow=20)
    database = SQLDatabase(engine)
    logger.info('Reconnected with database')
