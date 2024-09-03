#!/usr/bin/env python
import os
import sys
import json
import time
import select
import base64
import inspect
import argparse
import requests
import datetime
import sseclient
import subprocess
from halo import Halo

HIST_DIR = "/home/drewman/.config/"
HIST_FILE_POSTFIX = ""
HIST_FILE = lambda: HIST_DIR + "chatbuffer" + HIST_FILE_POSTFIX
MODELS = {"3.5": "gpt-3.5-turbo","4": "gpt-4", "4-turbo": "gpt-4-turbo-preview", "4o": "gpt-4o"}
DESC = "You are a helpful assistant."
URL = "https://api.openai.com/v1/chat/completions"
GPT_REQUEST_HEADERS = {
    "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
    "Accept": 'text / event - stream'
}
function_callback = None

parser = argparse.ArgumentParser()
parser.add_argument("-c", "--clear", help="Clear chat history file", action="store_true")
parser.add_argument("-co", "--chat-conversation", help="Chat conversation number")
parser.add_argument("-s", "--system", help="Set system prompt for this call", nargs="*", default=DESC)
parser.add_argument("-m", "--model", help="Specify GPT model to be used", default="4o", nargs="?")
parser.add_argument("-ci", "--clipboard-image", help="Use clipboard as image source", action="store_true")
parser.add_argument("input", help="Input prompt for chat", nargs="*")
args = None 

def get_clipboard_image():
    try:
        result = subprocess.run(['wl-paste', '-t', 'image/png'], stdout=subprocess.PIPE, check=True)
        image_data = result.stdout
        return base64.b64encode(image_data).decode('utf-8')
    except subprocess.CalledProcessError:
        print("Error: Couldn't get image from clipboard")
        sys.exit(1)




class GPTFunctions:

    @staticmethod
    def generate_image(image_description: str) -> str:
        """
        Generates an image based on parameter image_description which tells what the image should depict
        :param image_description:string:tells what the image should depict
        """
        from openai import OpenAI, BadRequestError
        from term_image.image import from_url
        client = OpenAI()
        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=image_description,
                size="1024x1024",
                quality="standard",
                n=1,
            )
        except BadRequestError as e:
            return "Failed to generate image: " + str(e)

        image_url = response.data[0].url
        assert image_url is not None
        im=from_url(image_url, width=50)
        global function_callback
        function_callback=lambda: im.draw(h_align="left", v_align="top", pad_height=1)
        return "Successfully generated and printed image to user";



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
            API_KEY="fdfcf91a7cd6e2c893ba090728bdbb3f"
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
    global function_callback
    function_callback = None
    spinner.start()
    res = getattr(GPTFunctions, name)(**args)
    spinner.succeed()
    if function_callback is not None:
        function_callback()
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
    with open(HIST_FILE(), 'a+') as f:
        f.seek(0)
        hist = [eval(i) for i in f]
    api_line = {
        "role": "user", 
        "content": user_line if args.clipboard_image is False else [
            {
                "type": "text",
                "text": user_line
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{get_clipboard_image()}"
                }
            }
        ]
    }
    messages = [
        {"role": "system", "content": args.system}, 
        *hist, 
        api_line, 
        *function_messages
    ]
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
    if args.chat_conversation:
        global HIST_FILE_POSTFIX
        HIST_FILE_POSTFIX = args.chat_conversation
    if args.clear:
        open(HIST_FILE(), 'w').close()
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
                time.sleep(0.004)
    print("")
    with open(HIST_FILE(), 'a') as f:
        f.write(json.dumps(user_line) + '\n')
        f.write(json.dumps({"role": "assistant", "content": complete_response}) + '\n')

if __name__ == "__main__":
    if select.select([sys.stdin,],[],[],0.0)[0]:
        stdin = [*sys.argv, *sys.stdin.read().strip().split(' ')]
        sys.argv = stdin
    args = parser.parse_args()
    main()

