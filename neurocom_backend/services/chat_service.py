from openai import OpenAI
from dotenv import load_dotenv
import os

_:bool = load_dotenv()

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=os.getenv("OPEN_ROUTER_AI_API_KEY"),
)

def get_chat_response_service(prompt):
    completion = client.chat.completions.create(
        # extra_headers={
        #     "HTTP-Referer": "<YOUR_SITE_URL>", # Optional. Site URL for rankings on openrouter.ai.
        #     "X-Title": "<YOUR_SITE_NAME>", # Optional. Site title for rankings on openrouter.ai.
        #     },
            extra_body={},
            model="qwen/qwen3-4b:free",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
                ]
            )
    content = completion.choices[0].message.content
    print(content)
    return content
