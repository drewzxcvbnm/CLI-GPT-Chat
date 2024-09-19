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
MODELS = {"3.5": "gpt-3.5-turbo","4": "gpt-4", "4-turbo": "gpt-4-turbo-preview", "4o": "gpt-4o", "o1": "o1-preview", "o1m": "o1-mini"}
DESC = "You an assistant that is helpful."
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

def detect_display_server():
    if 'WAYLAND_DISPLAY' in os.environ:
        return 'Wayland'
    if 'DISPLAY' in os.environ:
        return 'X11'
    return 'Unknown'

def get_clipboard_image_wayland():
    result = subprocess.run(['wl-paste', '-t', 'image/png'], stdout=subprocess.PIPE, check=True)
    image_data = result.stdout
    return base64.b64encode(image_data).decode('utf-8')

def get_clipboard_image_x11():
    result = subprocess.run(['xclip', '-selection', 'clipboard', '-t', 'image/png', '-o'], stdout=subprocess.PIPE, check=True)
    image_data = result.stdout
    return base64.b64encode(image_data).decode('utf-8')

def get_clipboard_image():
    try:
        if detect_display_server() == 'X11':
            return get_clipboard_image_x11()
        return get_clipboard_image_wayland()
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

def model():
    return MODELS[args.model]

def get_api_line(user_line):
    return {
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

def get_hist():
    with open(HIST_FILE(), 'a+') as f:
        f.seek(0)
        hist = [eval(i) for i in f]
    return hist

def gpt_function_call(complete_message, first_message):
    arguments = "".join([i['function_call']['arguments'] for i in complete_message if 'function_call' in i])
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
    return (function_call_message, function_response_message)

def create_message_generator(events_generator):
    def message_generator():
        for event in events_generator:
            if event.data != '[DONE]':
                yield json.loads(event.data)['choices'][0]['delta']
    return message_generator()


class SimpleO1Chat:

    def make_request(self, user_line):
        hist = get_hist()
        api_line = get_api_line(user_line)
        messages = self.get_messages(hist, api_line)
        data = self.get_data(messages)
        response = self.do_post(data)
        return json.loads(response.text)['choices'][0]['message']['content']

    def print_get_response(self, resp):
        print(resp)
        return resp

    def get_data(self, messages):
        return {
            "model": model(),
            "messages": messages,
            "stream": False,
        }

    def get_messages(self, hist, api_line):
        return [*hist, api_line]

    def do_post(self, data):
        return requests.post(URL, stream=False, headers=GPT_REQUEST_HEADERS, json=data)



class NormalChat:

    def make_request(self, user_line, function_messages=()):
        hist = get_hist()
        api_line = get_api_line(user_line)
        messages = self.get_messages(hist, api_line, function_messages)
        data = self.get_data(messages)
        response = self.do_post(data)
        client = sseclient.SSEClient(response)
        events_generator = client.events()
        resp_data = next(events_generator).data
        first_message = json.loads(resp_data)['choices'][0]['delta']
        if first_message.get("function_call"):
            complete_message = [json.loads(i.data)['choices'][0]['delta'] for i in events_generator if i.data != '[DONE]']
            client.close()
            return self.make_request(user_line, (*function_messages, *gpt_function_call(complete_message, first_message)))
        return create_message_generator(events_generator)


    def print_get_response(self, resp):
        complete_response = ""
        for i in resp:
            if 'content' in i:
                complete_response += i['content']
                for ch in i['content']:
                    print(ch, end="", flush=True)
                    time.sleep(0.004)
        print("")
        return complete_response

    def get_data(self, messages):
        return {
            "model": model(),
            "messages": messages,
            "stream": True,
            "functions": create_functions()
        }

    def get_messages(self, hist, api_line, function_messages):
        sys = {"role": "system", "content": args.system}
        return [sys, *hist, api_line, *function_messages]

    def do_post(self, data):
        return requests.post(URL, stream=True, headers=GPT_REQUEST_HEADERS, json=data)


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
    user_line = str.join(' ', args.input)
    chat = SimpleO1Chat() if model() in ('o1-preview', 'o1-mini') else NormalChat()
    resp = chat.make_request(user_line)
    complete_response = chat.print_get_response(resp)
    with open(HIST_FILE(), 'a') as f:
        f.write(json.dumps(get_api_line(user_line)) + '\n')
        f.write(json.dumps({"role": "assistant", "content": complete_response}) + '\n')

if __name__ == "__main__":
    if select.select([sys.stdin,],[],[],0.0)[0]:
        stdin = [*sys.argv, *sys.stdin.read().strip().split(' ')]
        sys.argv = stdin
    args = parser.parse_args()
    main()

