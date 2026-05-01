from ollama import Client
from openai import OpenAI


class ChatBotClient():

    def __init__(self, name="3po", model="phi3:mini", host='http://localhost:11434', headers={'x-some-header': 'some-value'}):
        self.host = host
        self.name = name
        self.model = model
        self.client = Client(host=self.host, headers=headers)
        # self.client = OpenAI(api_key="EMPTY", base_url="http://10.209.93.21:8000/v1")  # use this if switching to OpenAI-compatible API
        self.messages = []
    
    def chat(self, message: str):
        # If you want context, you can add previous conversation history
        self.messages.append({"role": "user", "content": message})

        response = self.client.chat(
            self.model,
            messages=self.messages
        )
        msg = response["message"]["content"]

        # Add assistant's response to the conversation context
        self.messages.append({"role": "assistant", "content": msg})
        return msg
    
    def stream_chat(self, message):
        self.messages.append({
            'role': 'user',
            'content': message,
        })
        response = self.client.chat(self.model, self.messages, stream=True)
        answer = ""
        for chunk in response:
            piece = chunk["message"]["content"]
            print(piece, end="")
            answer += piece
        self.messages.append({"role": "assistant", "content": answer})


class ChatBotClientOpenAI():
    def __init__(self, name="3po", model="phi3:mini", host='http://localhost:11434', headers={'x-some-header': 'some-value'}):
        self.host = host
        self.name = name
        self.model = model
        self.client = OpenAI(api_key="EMPTY", base_url="http://10.209.93.21:8000/v1")  # use other port if necessary
        self.messages = []

    def chat(self, messages):
        model_id = "/home/nlp/.cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B-Instruct/snapshots/7ae557604adf67be50417f59c2c2f167def9a775"
        # Example system prompt (commented out):
        # messages = [
        #     {"role": "system", "content": f"Enter role play mode. You are {self.name}, a professional academic advisor at NYU Shanghai. Reply warmly, within 20 words."},
        #     {"role": "user", "content": query + "/no_think"},
        # ]

        response = self.client.chat.completions.create(
            messages=messages,
            model=model_id,
            temperature=0.3,
        )
        return response.choices[0].message.content
    

if __name__ == "__main__":
    c = ChatBotClient()
    print(c.chat("Your name is Tom, and you are the learning assistant of Python programming."))
    print(c.stream_chat("What's your name and role?"))