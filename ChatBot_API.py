from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, request, jsonify, make_response, render_template, session, redirect, flash
import jwt
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
import os
from ChatBot_PoC import agent, prompt, reconnect_db, jwt_token_expiration, jwt_algorithm, logger
from langchain_community.callbacks import get_openai_callback
from sqlalchemy import create_engine, insert, text, MetaData, select


app = Flask(__name__)


# Setup Azure Key Vault client
credential = DefaultAzureCredential()
key_vault_url = "https://domain.vault.azure.net/"
secret_client = SecretClient(vault_url=key_vault_url, credential=credential)

# # Fetch secrets from Key Vault
# bi_db_connection_string = secret_client.get_secret("BI-DB-CONNECTION-STRING").value
# user_authentication_key = secret_client.get_secret("USER-AUTHENTICATION-KEY").value

bi_db_connection_string = "mssql+pyodbc://USER:PASSWORD@DB-SERVER/DB?driver=ODBC+Driver+17+for+SQL+Server"
user_authentication_key = "<JWT TOKEN KEY>"

# Set JWT Authentication key
jwt_secrets = user_authentication_key
app.config['SECRET_KEY'] = jwt_secrets
algorithm = jwt_algorithm


# set global variables
result = ""
web_result = ""
data = {}


# Connect with Read-Write database for logging
try:
    logger.info("Connecting to database bi-db-india-region")
    crud_engine = create_engine(bi_db_connection_string, pool_size=10, max_overflow=20) #db_connection_string
    meta = MetaData()
    meta.reflect(bind=crud_engine)
    logger.info('Connected with database bi-db-india-region')
except Exception as e:
    logger.error('Problem in connecting with database:',str(e))


def token_required(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        global web_result

        try:
            token = request.get_json()['token']
            if not token:
                logger.error('Invalid request format. Token is missing.')
                web_result = "Token is missing! 401"
                return jsonify({'result': 'Token is missing!'}), 401
        except Exception as e:
            web_result = e
            logger.error('Invalid request format. Token is missing.')
            return jsonify({'result': 'Token is missing!'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithm)
        except Exception as e:
            web_result = e
            logger.error('Invalid token for user ' + request.get_json()['user_name'])
            return jsonify({'result': 'Invalid token. Please login again!'}), 403
        logger.info("Token verified!")
        return func(*args, **kwargs)
    return decorated


@app.route('/login', methods=['POST'])
def login():
    global data, user_id, user_name, password
    try:  # check JSON format and pass an error if incorrect
        data = request.get_json()
        user_id = data['user_id']
        user_name = data['user_name']
        password = data['password']
    except Exception as param_missing:
        logger.error('Invalid request format while log in.'+str(data)+': '+str(param_missing))
        return jsonify([{'result': "Not Acceptable. Invalid request format. "+str(param_missing)}]), 406

    try:  # fetch password from chatbot_user_login table
        logger.info('Fetching password for user ' + user_name)
        login_conn = crud_engine.connect()
        user_table = meta.tables['chatbot_user_login']
        user_password = select(user_table).where(user_table.c["User Name"] == user_name)
        user_password = login_conn.execute(user_password).fetchone()[2]
        logger.info('Fetched password for ' + user_name)
    except Exception as login_failed:
        logger.error('Could not fetch password from database. Please contact admin for registration!'+str(data)+': '+str(login_failed))
        return jsonify([{'result': "Problem in login. Please contact admin for registration!"}])

    # verify password and generate token
    if user_name and password == user_password:
        session['logged_in'] = True
        session["name"] = user_name
        payload = {
            'user_id': request.get_json()['user_id'],
            'exp': datetime.now(timezone.utc) + timedelta(seconds=jwt_token_expiration)
        }
        bearer_token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm)
        logger.info('Token generated for user ' + user_name)
        return jsonify({'token': bearer_token})
    else:
        return make_response('Unable to verify', 403, {'WWW-Authenticate': 'Basic realm: "Authentication Failed"'})

@app.route('/hello/', methods=['GET', 'POST'])
def welcome():  # Just to test if server is up and running
    return "Hello World!"


@app.route('/query/', methods=['POST'])
@token_required
def ask_chatbot():
    """JSON data should be passed while requesting '/query/' endpoint"""

    global result, web_result, data
    exception = output = intermediate_steps = ''

    try:  # check JSON format and pass an error if incorrect
        data = request.get_json()
        question = data['question']
        user_id = data['user_id']
        user_name = data['user_name']
    except Exception as param_missing:
        logger.error('Invalid request format '+str(data)+': '+str(param_missing))
        return jsonify([{'result': "Invalid request format. missing "+str(param_missing)}])

    with get_openai_callback() as cb:
        try:  # try to get result
            logger.info('Chatbot is generating answer')
            result = agent(prompt.format_prompt(question=question))
        except:  # if DB is disconnected due to idle state, reconnect and try again
            logger.info('Trying to reconnect with database and generate answer')
            reconnect_db()
            try:  # try again to get the result
                result = agent(prompt.format_prompt(question=question))
            except Exception as chatbot_failed:  # log and return error
                logger.error("Failed to run chatbot! : "+str(exception))
                exception = web_result = chatbot_failed
                log_data(user_id, user_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                         question, '', '',
                         cb.total_tokens, cb.total_cost, exception if exception else '')
                return jsonify([{'result': "Failed to run chatbot! : "+str(exception)}])

        # log data and return result
        log_data(user_id, user_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 result['input'].to_messages()[1].content, result['output'], result['intermediate_steps'],
                 cb.total_tokens, cb.total_cost,exception if exception else '')
        web_result = result['output']
        return jsonify([{'result': result['output']}])


@app.route('/result/', methods=['GET'])
def get_result():
    """To check result on webpage"""
    return web_result


def log_data(user_id, user_name, date_time, question, answer, intermediate_steps, tokens, cost, exception):
    global crud_engine, web_result
    conn = crud_engine.connect()
    logger.info('Logging data.')
    try:
        conn.execute(meta.tables['chatbot_user_usage'].insert().values([{'User ID': user_id, 'User Name': user_name,
                                                                         'Date Time': date_time, 'Question': question,
                                                                         'Answer': answer,
                                                                         # 'Intermediate Steps': str(intermediate_steps),
                                                                         'Tokens': tokens, 'Cost': cost,
                                                                         'Exception': exception}]))
        conn.commit()
        conn.close()
        logger.info(f"{user_id} | {user_name} | {date_time} | {question} | {answer} | {str(intermediate_steps)} "
                    f"| {tokens} | {cost} | {exception}")
    except Exception as e:
        logger.error('Error occurred while logging:' + str(e))
        try:
            logger.info('Trying to write again..')
            conn.rollback()
            conn.execute(meta.tables['chatbot_user_usage'].insert().values([{'User ID': user_id, 'User Name': user_name,
                                                                             'Date Time': date_time, 'Question': question,
                                                                             'Answer': answer,
                                                                             # 'Intermediate Steps': str(intermediate_steps),
                                                                             'Tokens': tokens, 'Cost': cost,
                                                                             'Exception': exception}]))
            conn.commit()
            conn.close()
            logger.info(f"{user_id} | {user_name} | {date_time} | {question} | {answer} | {str(intermediate_steps)} "
                        f"| {tokens} | {cost} | {exception}")
        except Exception as e:
            web_result = e
            logger.exception("Couldn't log data:" + str(e))
    logger.info('Data logged.')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=105)
