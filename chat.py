#!/usr/bin/env python
import os
import re
import sys
import json
import time
import select
import inspect
import argparse
import requests
import datetime
import sseclient
from halo import Halo

HIST_FILE = f"{os.environ['HOME']}/.config/chatbuffer"
MODELS = {"3.5": "gpt-3.5-turbo", "4": "gpt-4"}
DESC = "You are a helpful assistant who answers questions and inquiries."
URL = "https://api.openai.com/v1/chat/completions"
GPT_REQUEST_HEADERS = {
    "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
    "Accept": 'text / event - stream'
}

parser = argparse.ArgumentParser()
parser.add_argument("-c", "--clear", help="Clear chat history file", action="store_true")
parser.add_argument("-s", "--system", help="Set system prompt for this call", nargs="*", default=DESC)
parser.add_argument("-m", "--model", help="Specify GPT model to be used", default="4", nargs="?")
parser.add_argument("input", help="Input prompt for chat", nargs="*")
args = None 


class GPTFunctions:

    @staticmethod
    def get_time():
        """
        Gets the current time
        """
        return str(datetime.datetime.now())

    @staticmethod
    def get_location_city():
        try:
            response = requests.get("https://ipinfo.io/json")
            if response.status_code == 200:
                data = response.json()
                return data.get("city")
            else:
                return "Error: Unable to fetch data."
        except Exception as e:
            return f"An error occurred: {e}"

    @staticmethod
    def get_weather(city: str):
        """
        Gets the weather
        :param city:string:City whose weather to get
        """
        try:
            API_KEY=os.environ['OPEN_WEATHER_KEY']
            UNITS="metric"
            UNIT_KEY="C"
            response = requests.get(f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={API_KEY}&units={UNITS}")
            if response.status_code == 200:
                data = response.json()
                main = data['main']
                weather = data['weather'][0]
                return {
                    "city": data["name"],
                    "temperature": f'{main["temp"]}°C',
                    "pressure": main["pressure"],
                    "humidity": main["humidity"],
                    "weather": weather["main"],
                    "description": weather["description"]
                }
            else:
                return "Error: Unable to fetch data."
        except Exception as e:
            return f"An error occurred: {e}"


def concat_dict(dicts: list[dict]):
    concatenated_dict = {}
    for d in dicts:
        concatenated_dict.update(d)
    return concatenated_dict


def create_arg(name: str, arg_type: str, desc: str) -> dict:
    return {
        name: {
            "type": arg_type,
            "description": desc
        }
    }


def create_function(name: str, desc: str = "", fargs=()):
    arguments = concat_dict(fargs)
    return {
        "name": name,
        "description": desc,
        'parameters': {
            "type": "object",
            "properties": arguments,
            "required": [*arguments.keys()]
        }
    }


def call_function(name: str, args=None):
    if args is None:
        args = {}
    spinner = Halo(text=f"Calling function {name}", spinner='dots')
    spinner.start()
    res = getattr(GPTFunctions, name)(*args)
    spinner.succeed()
    return res


def docstring_param_to_arg(param_doc: str):
    param_doc = param_doc.replace(':param', '')
    name, type, desc = [i.strip() for i in param_doc.split(':')]
    return create_arg(name, type, desc)


def create_functions():
    members = inspect.getmembers(GPTFunctions, predicate=inspect.isfunction)
    functions = []
    for mem in members:
        name = mem[0]
        doc = mem[1].__doc__
        if doc is None:
            functions.append(create_function(name))
            continue
        desc = doc.split('\n')[1].strip()
        fargs = (docstring_param_to_arg(i) for i in doc.split('\n') if i.strip().startswith(':param'))
        functions.append(create_function(name, desc, fargs))
    return functions


def make_request(user_line, function_messages=()):
    with open(HIST_FILE, 'r') as f:
        hist = [eval(i) for i in f]
    api_line = {"role": "user", "content": user_line}
    messages = [{"role": "system", "content": args.system}, *hist, api_line, *function_messages]
    data = {
        "model": MODELS[args.model],
        "messages": messages,
        "stream": True,
        "functions": create_functions()
    }
    response = requests.post(URL, stream=True, headers=GPT_REQUEST_HEADERS, json=data)
    client = sseclient.SSEClient(response)
    events_generator = client.events()
    resp_data = next(events_generator).data
    try:
        first_message = json.loads(resp_data)['choices'][0]['delta']
    except Exception as e:
        print(f"Got error: {e}")
        print(f"Received data: {resp_data}")
        sys.exit(1)
    if first_message.get("function_call"):
        complete_message = [json.loads(i.data)['choices'][0]['delta'] for i in events_generator if i.data != '[DONE]']
        arguments = "".join([i['function_call']['arguments'] for i in complete_message if 'function_call' in i])
        client.close()
        function_name = first_message["function_call"]["name"]
        function_response = call_function(function_name, json.loads(arguments))
        function_call_message = {
            "content": None,
            "function_call": first_message["function_call"],
            "role": "assistant",
        }
        function_response_message = {
            "role": "function",
            "name": function_name,
            "content": str(function_response),
        }
        return make_request(user_line, (*function_messages, function_call_message, function_response_message))

    def message_generator():
        for event in events_generator:
            if event.data != '[DONE]':
                yield json.loads(event.data)['choices'][0]['delta']

    return message_generator()


def main():
    if len(sys.argv) < 2:
        print("No arguments given")
        return
    if args.clear:
        open(HIST_FILE, 'w').close()
        print("Deleted history")
    if len(args.input) == 0:
        return
    user_line = {"role": "user", "content": str.join(' ', args.input)}
    response_generator = make_request(str.join(' ', args.input))
    complete_response = ""
    for i in response_generator:
        if 'content' in i:
            complete_response += i['content']
            for ch in i['content']:
                print(ch, end="", flush=True)
                time.sleep(0.010)
    print("")
    with open(HIST_FILE, 'a') as f:
        f.write(json.dumps(user_line) + '\n')
        f.write(json.dumps({"role": "assistant", "content": complete_response}) + '\n')

if __name__ == "__main__":
    if select.select([sys.stdin,],[],[],0.0)[0]:
        stdin = [*sys.argv, *sys.stdin.read().strip().split(' ')]
        sys.argv = stdin
    args = parser.parse_args()
    main()

