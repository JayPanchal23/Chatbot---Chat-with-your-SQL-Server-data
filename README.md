# Chatbot---Chat-with-your-SQL-Server-data
A GenAI solution which allows you to chat with your SQL data using LangChain, OpenAI and SQLAlchemy.

* ChatBot_PoC.py:
  - contains core logic used to develop chatbot using langchain and openAI.
  - Tested using gpt-4o-mini
  - Prompt is supplied to train the model and get accurate answers
  - Configuraion details are stored in DB to tune change the model from backend without touching code.
  - Agent is created using toolkits which allows to connect with Database and prepares answer for user.
* ChatBot_API.py:
  - Developed API endpoints using Flask API.
  - Added JWT Token based User Authentication for limited access.
  - Logging errors and user usage in betterstack platform
  - Login using ID Password to get token
  - pass token along with User Query to get answer from SQL database.
* Chatbot_UI.py
  - Simple tkinter based GUI
  - prototype built to showcase how chatbot works.
