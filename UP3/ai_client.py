import json
import requests
from openai import OpenAI

client = OpenAI(
    api_key="EMPTY", 
    base_url="http://10.208.2.89:8000/v1"
)

# Path to the locally hosted or custom model
MODEL_ID = "/home/nlp/.cache/modelscope/hub/models/Qwen/Qwen3-VL-8B-Instruct-FP8"


def ask_llm(prompt: str) -> str:
    """
    Send a plain text query to the custom LLM/VLM API and return the response text.
    The input is a string, and the output is the model's generated answer.
    """
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
            ],
        }
    ]

    resp = client.chat.completions.create(
        model=MODEL_ID,
        messages=messages,
        temperature=0.6,
    )

    return resp.choices[0].message.content


if __name__ == "__main__":
    print(ask_llm("Who are you?"))