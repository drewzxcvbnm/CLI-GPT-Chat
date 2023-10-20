# CLI GPT Chat

## Description
A Python script interface to interact with OpenAI's GPT models (3.5 and 4) for chat-based completions. The script supports multiple functionalities such as fetching the current time, getting the city based on IP, and checking the weather for a specified city.

## Dependencies
The script requires several Python libraries. You can install them using `pip`:
```
pip install -r requirements.txt
```

## Setup

1. **API Key:** The script expects the OpenAI API key to be set in an environment variable named `OPENAI_API_KEY`.

2. **History File:** The script maintains a history of chat interactions in a file. By default, the path is `~/.config/chatbuffer`. Ensure you have write permissions to this directory or modify the path in the script.

## Usage

```
usage: chat [-h] [-c] [-s [SYSTEM ...]] [-m [MODEL]] [input ...]

positional arguments:
  input                 Input prompt for chat

options:
  -h, --help            show this help message and exit
  -c, --clear           Clear chat history file
  -s [SYSTEM ...], --system [SYSTEM ...]
                        Set system prompt for this call
  -m [MODEL], --model [MODEL]
                        Specify GPT model to be used

Examples:
> chat -m 3.5 "Tell me a joke"
> chat Tell me a joke
> echo "Tell me a joke" | chat
> chat << EOF
Tell me a Joke
EOF
```

## Additional Information
The script utilizes streaming output, displaying chat responses character by character, to make the chat a bit less boring. Also contains integrated function call capabilities for specific tasks.

### History
The script maintains a history of previous interactions in the chat history file, making the conversation context-aware. You can clear this history using the `-c` flag. (file where chat history is stored may need to be created in advance)

